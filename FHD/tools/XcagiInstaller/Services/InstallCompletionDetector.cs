namespace XcagiInstaller.Services;

/// <summary>
/// Required-file validation after the installer has exited successfully.
/// </summary>
public static class InstallCompletionDetector
{
    public static bool IsComplete(string installDirectory)
    {
        if (string.IsNullOrWhiteSpace(installDirectory) || !Directory.Exists(installDirectory))
            return false;

        var appExe = Path.Combine(installDirectory, "XCAGI.exe");
        if (!File.Exists(appExe))
            return false;

        var asar = Path.Combine(installDirectory, "resources", "app.asar");
        if (!File.Exists(asar))
            return false;

        var backend = Path.Combine(installDirectory, "resources", "backend", "xcagi-backend.exe");
        return File.Exists(backend);
    }
}
