using System.Diagnostics;

namespace XcagiInstaller.Services;

public static class InstallProgressTracker
{
    // Stage markers only: installed files never imply the child exited successfully.
    public static async Task MonitorInstallAsync(
        Process process, string installDirectory,
        IProgress<InstallProgressUpdate>? progress, CancellationToken cancellationToken = default)
    {
        var lastReported = -1;
        while (!process.HasExited)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var percent = InstallCompletionDetector.IsComplete(installDirectory) ? 95
                : File.Exists(Path.Combine(installDirectory, "resources", "app.asar")) ? 65
                : File.Exists(Path.Combine(installDirectory, "XCAGI.exe")) ? 35 : 0;
            if (percent > lastReported)
            {
                lastReported = percent;
                progress?.Report(new InstallProgressUpdate(percent, percent == 95
                    ? "正在等待安装进程完成…" : percent == 0 ? "正在初始化安装…" : "正在部署应用文件…"));
            }
            await Task.Delay(1000, cancellationToken).ConfigureAwait(false);
        }
    }
}
