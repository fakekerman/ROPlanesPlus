using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace ROPlanesPlus
{
    /// <summary>
    /// Builds "Custom Paint" livery textures at runtime. generate_propeller_assets.py writes a paint
    /// kit next to the livery maps:
    ///   ropp_paintkit_base.dat  PNG, RGBA: unpainted texels hold their final colour + gloss;
    ///                           painted texels hold a grey shade (200 = clean paint) + gloss factor
    ///   ropp_paintkit_mask.dat  PNG, R channel: 0 unpainted, 85 cowling, 170 nose ring, 255 spinner
    /// (".dat" so KSP's GameDatabase doesn't load them as textures). Results are cached per colour
    /// combination, so symmetric engines share one texture.
    /// </summary>
    public static class CustomPaint
    {
        private const string KitDir = "GameData/ROPlanesPlus/Parts/PropShared/";

        private static Color32[] _base;
        private static byte[] _mask;
        private static int _w;
        private static int _h;
        private static bool _loadFailed;
        private static readonly Dictionary<string, Texture2D> _cache = new Dictionary<string, Texture2D>();

        public static Color32 ParseColor(string hex, Color32 fallback)
        {
            if (string.IsNullOrEmpty(hex))
                return fallback;
            string s = hex.Trim().TrimStart('#');
            if (s.Length != 6)
                return fallback;
            try
            {
                byte r = Convert.ToByte(s.Substring(0, 2), 16);
                byte g = Convert.ToByte(s.Substring(2, 2), 16);
                byte b = Convert.ToByte(s.Substring(4, 2), 16);
                return new Color32(r, g, b, 255);
            }
            catch (FormatException)
            {
                return fallback;
            }
        }

        public static string ToHex(Color32 c)
        {
            // No leading "#": KSP treats config values starting with "#" as localization tags
            return c.r.ToString("X2") + c.g.ToString("X2") + c.b.ToString("X2");
        }

        private static bool EnsureKit()
        {
            if (_base != null)
                return true;
            if (_loadFailed)
                return false;
            try
            {
                string root = KSPUtil.ApplicationRootPath;
                Texture2D tb = LoadPng(Path.Combine(root, KitDir + "ropp_paintkit_base.dat"));
                Texture2D tm = LoadPng(Path.Combine(root, KitDir + "ropp_paintkit_mask.dat"));
                if (tb.width != tm.width || tb.height != tm.height)
                    throw new InvalidDataException("paint kit base and mask sizes differ");
                _w = tb.width;
                _h = tb.height;
                _base = tb.GetPixels32();
                Color32[] m = tm.GetPixels32();
                _mask = new byte[m.Length];
                for (int i = 0; i < m.Length; i++)
                    _mask[i] = m[i].r;
                UnityEngine.Object.Destroy(tb);
                UnityEngine.Object.Destroy(tm);
                return true;
            }
            catch (Exception ex)
            {
                _loadFailed = true;
                Debug.LogError("[ROPlanesPlus] could not load the custom paint kit: " + ex.Message);
                return false;
            }
        }

        private static Texture2D LoadPng(string path)
        {
            byte[] bytes = File.ReadAllBytes(path);
            Texture2D t = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            if (!ImageConversion.LoadImage(t, bytes, false))
                throw new InvalidDataException("not a PNG: " + path);
            return t;
        }

        private static byte Scale(byte c, float s)
        {
            float v = c * s;
            return (byte)(v < 0f ? 0f : (v > 255f ? 255f : v));
        }

        /// <summary>Returns the composited livery, or null if the kit is missing.</summary>
        public static Texture2D GetTexture(Color32 cowl, Color32 nose, Color32 spinner, int finish)
        {
            int f = Mathf.Clamp(finish, 0, PropellerPresets.FinishGloss.Length - 1);
            string key = ToHex(cowl) + ToHex(nose) + ToHex(spinner) + f;
            Texture2D cached;
            if (_cache.TryGetValue(key, out cached) && cached != null)
                return cached;
            if (!EnsureKit())
                return null;

            byte gloss = PropellerPresets.FinishGloss[f];
            Color32[] outPx = new Color32[_base.Length];
            for (int i = 0; i < outPx.Length; i++)
            {
                byte m = _mask[i];
                Color32 b = _base[i];
                if (m < 40)
                {
                    outPx[i] = b;
                    continue;
                }
                Color32 c = m < 128 ? cowl : (m < 213 ? nose : spinner);
                float shade = b.r / 200f;
                outPx[i] = new Color32(Scale(c.r, shade), Scale(c.g, shade), Scale(c.b, shade), (byte)(gloss * b.a / 255));
            }

            Texture2D tex = new Texture2D(_w, _h, TextureFormat.RGBA32, true);
            tex.name = "ropp_custom_" + key;
            tex.wrapMode = TextureWrapMode.Repeat;
            tex.anisoLevel = 4;
            tex.SetPixels32(outPx);
            tex.Apply(true, false);
            tex.Compress(true);
            tex.Apply(false, true);
            _cache[key] = tex;
            return tex;
        }
    }
}
