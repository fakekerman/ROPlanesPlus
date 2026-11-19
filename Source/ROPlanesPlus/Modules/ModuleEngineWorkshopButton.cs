namespace ROPlanesPlus
{
    /// <summary>
    /// Holds only the "Open Engine Workshop" part-menu button. It is the first MODULE in the part
    /// cfg so the button sits at the very top of the right-click menu, above the engine's own
    /// entries, without changing the start-up order of the engine modules themselves.
    /// </summary>
    public class ModuleEngineWorkshopButton : PartModule
    {
        [KSPEvent(guiActiveEditor = true, guiActive = true, guiName = "<b><color=#FFB040>Open Engine Workshop</color></b>")]
        public void OpenWorkshopEvent()
        {
            ModuleProceduralPropeller m = part.FindModuleImplementing<ModuleProceduralPropeller>();
            if (m != null)
                EngineWorkshopWindow.Toggle(m);
        }

        public override string GetInfo()
        {
            return string.Empty;
        }
    }
}
