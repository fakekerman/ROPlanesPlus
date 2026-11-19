using System;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>
    /// Fast analytic performance estimate used by the Engine Workshop charts and for the stock
    /// fallback thrust. In flight with AJE the real numbers come from AJE; this model follows the
    /// same AJE parameters (supercharger stages, rated altitudes, BSFC) so the charts match what
    /// the engine will do closely enough to compare designs.
    /// </summary>
    public static class PerformanceModel
    {
        public const float HPToW = 745.699872f;

        public static void Atmosphere(float altM, out float rho, out float speedOfSound, out float sigma)
        {
            float h = Mathf.Max(0f, altM);
            float T;
            float p;
            if (h < 11000f)
            {
                T = 288.15f - 0.0065f * h;
                p = 101325f * Mathf.Pow(T / 288.15f, 5.2559f);
            }
            else
            {
                T = 216.65f;
                p = 22632f * Mathf.Exp(-(h - 11000f) / 6341.6f);
            }
            rho = p / (287.05f * T);
            speedOfSound = Mathf.Sqrt(1.4f * 287.05f * T);
            sigma = rho / 1.225f;
        }

        private static float Sigma(float altM)
        {
            float rho, a, s;
            Atmosphere(altM, out rho, out a, out s);
            return s;
        }

        // A supercharger stage holds its rated power up to its rated altitude, then loses power
        // roughly with density^1.1 (same behaviour AJE's piston model shows above full-throttle height).
        private static float StagePower(float ratedHP, float ratedAlt, float alt, float sigma)
        {
            if (alt <= ratedAlt)
                return ratedHP;
            return ratedHP * Mathf.Pow(sigma / Sigma(ratedAlt), 1.1f);
        }

        /// <summary>Maximum shaft power (hp) at an altitude; mult = 1 dry, wepMultiplier wet.</summary>
        public static float PowerHP(AJEParameters a, bool turboprop, float altM, float mult)
        {
            if (a == null)
                return 0f;
            float s = Sigma(altM);
            float p0 = (float)a.power * mult;
            if (turboprop)
                return p0 * Mathf.Pow(s, 0.75f);
            if (a.turbo)
                return StagePower(p0, (float)Math.Max(0.0, a.rated0), altM, s);
            if (a.boost0 <= 0.01)
                return p0 * Mathf.Pow(s, 1.1f);
            float best = StagePower(p0, (float)Math.Max(0.0, a.rated0), altM, s);
            if (a.rated1 > 0.0)
                best = Mathf.Max(best, StagePower(p0 - (float)a.cost1 * mult, (float)a.rated1, altM, s));
            return best;
        }

        /// <summary>
        /// Propeller thrust (kN) from momentum theory with a speed-dependent efficiency, tip
        /// compressibility loss, and residual jet thrust for turboprops.
        /// </summary>
        public static float ThrustKN(float shaftHP, float propDiameter, bool contra, bool turboprop,
                                     double exhaustThrust, float maxPropRPM, float speedMS, float altM)
        {
            if (shaftHP <= 0f || propDiameter <= 0.1f)
                return 0f;
            float rho, snd, sigma;
            Atmosphere(altM, out rho, out snd, out sigma);
            float area = 0.25f * Mathf.PI * propDiameter * propDiameter;
            float v = Mathf.Max(0f, speedMS);

            // Single props lose energy to slipstream swirl, more the harder they are loaded;
            // a contra-prop's rear row recovers ~80 % of it.
            float swirlFactor = 1f - SwirlLoss(shaftHP, propDiameter) * (contra ? 0.2f : 1f);
            float etaStatic = 0.66f * swirlFactor;
            float etaCruise = 0.90f * swirlFactor;
            float t = Mathf.Clamp01(v / 70f);
            float eta = Mathf.Lerp(etaStatic, etaCruise, t * t * (3f - 2f * t));
            float pe = eta * shaftHP * HPToW;

            // Solve T * (V + vi) = Pe, vi = induced velocity from actuator-disk theory
            float lo = 0f;
            float hi = Mathf.Pow(2f * rho * area * pe * pe, 1f / 3f) * 1.05f + 1f;
            for (int i = 0; i < 40; i++)
            {
                float mid = 0.5f * (lo + hi);
                float vi = -0.5f * v + Mathf.Sqrt(0.25f * v * v + mid / (2f * rho * area));
                if (mid * (v + vi) > pe) hi = mid;
                else lo = mid;
            }
            float thrust = 0.5f * (lo + hi);

            float tipSpeed = Mathf.PI * propDiameter * maxPropRPM / 60f;
            float helicalMach = Mathf.Sqrt(tipSpeed * tipSpeed + v * v) / snd;
            if (helicalMach > 0.85f)
                thrust *= Mathf.Max(0.35f, 1f - 1.6f * (helicalMach - 0.85f));

            if (turboprop)
                thrust += shaftHP * 0.65f * (float)exhaustThrust * Mathf.Max(0.5f, 1f - v / 500f);

            return thrust * 0.001f;
        }

        /// <summary>Fraction of power lost to swirl by a single-rotation prop (2 % .. 15 %).</summary>
        public static float SwirlLoss(float shaftHP, float propDiameter)
        {
            float area = 0.25f * Mathf.PI * propDiameter * propDiameter;
            float diskLoadingKW = shaftHP * 0.7457f / Mathf.Max(0.5f, area);
            return Mathf.Clamp(0.02f + 0.00035f * diskLoadingKW, 0.02f, 0.15f);
        }

        /// <summary>Thrust multiplier of a contra-prop over a single prop of the same size and power.</summary>
        public static float ContraThrustGain(float shaftHP, float propDiameter)
        {
            float s = SwirlLoss(shaftHP, propDiameter);
            return (1f - 0.2f * s) / (1f - s);
        }

        public static float HelicalTipMach(float propDiameter, float maxPropRPM, float speedMS, float altM)
        {
            float rho, snd, sigma;
            Atmosphere(altM, out rho, out snd, out sigma);
            float tip = Mathf.PI * propDiameter * maxPropRPM / 60f;
            return Mathf.Sqrt(tip * tip + speedMS * speedMS) / snd;
        }

        /// <summary>Fuel burn at a shaft power, in litres per hour.</summary>
        public static float FuelLitresPerHour(double bsfc, float shaftHP, string fuel)
        {
            float density = string.Equals(fuel, "Kerosene", StringComparison.OrdinalIgnoreCase) ? 0.80f : 0.72f;
            return (float)bsfc * shaftHP * HPToW * 3600f / density;
        }

        /// <summary>Altitude (m) above which the engine makes less than half its sea-level power.</summary>
        public static float HalfPowerAltitude(AJEParameters a, bool turboprop)
        {
            float p0 = PowerHP(a, turboprop, 0f, 1f);
            for (float h = 0f; h <= 16000f; h += 100f)
            {
                if (PowerHP(a, turboprop, h, 1f) < 0.5f * p0)
                    return h;
            }
            return 16000f;
        }
    }
}
