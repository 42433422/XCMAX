using System.Diagnostics;

namespace XcagiInstaller.Services;

public sealed class NsisSilentInstaller
{
    public static void Trace(string message)
    {
        try { File.AppendAllText(Path.Combine(Path.GetTempPath(), "xcagi-installer-silent.log"), $"[{DateTimeOffset.UtcNow:O}] {message}{Environment.NewLine}"); }
        catch { /* Diagnostics cannot change the installation result. */ }
    }

    public static string DefaultInstallDirectory()
    {
        var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(local, "Programs", "XCAGI");
    }

    /// <summary>
    /// 静默运行 NSIS：/S 静默，/D= 必须为最后一个参数且路径勿加引号。
    /// </summary>
    public static async Task<InstallResult> RunAsync(
        string setupExePath,
        string installDirectory,
        IProgress<InstallProgressUpdate>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (!File.Exists(setupExePath))
            return InstallResult.Fail($"未找到安装包：{setupExePath}");

        var dir = installDirectory.Trim().TrimEnd('\\', '/');
        if (string.IsNullOrWhiteSpace(dir))
            return InstallResult.Fail("安装目录无效。");

        try
        {
            Directory.CreateDirectory(dir);
        }
        catch (Exception ex)
        {
            return InstallResult.Fail($"无法创建目录：{ex.Message}");
        }

        var args = $"/S /D={dir}";
        Trace($"install requested: payload={setupExePath};target={dir}");
        var psi = new ProcessStartInfo
        {
            FileName = setupExePath,
            Arguments = args,
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };

        using var process = new Process { StartInfo = psi, EnableRaisingEvents = true };
        try
        {
            if (!process.Start())
                return InstallResult.Fail("无法启动安装进程。");
            Trace($"child started: pid={process.Id}");
        }
        catch (Exception ex)
        {
            Trace($"child start failed: {ex}");
            return InstallResult.Fail($"启动失败：{ex.Message}");
        }

        var estimated = InstallProgressTracker.EstimateInstalledBytes(setupExePath, dir);

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromMinutes(30));
        try
        {
            await InstallProgressTracker.MonitorInstallAsync(
                process, dir, estimated, progress, timeout.Token).ConfigureAwait(false);
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            Trace(cancellationToken.IsCancellationRequested ? "installation cancelled" : "installation timed out");
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                    await process.WaitForExitAsync(CancellationToken.None).ConfigureAwait(false);
                }
            }
            catch { /* Cancellation remains a failure even if stopping the installer fails. */ }
            return InstallResult.Fail(cancellationToken.IsCancellationRequested ? "安装已取消。" : "安装超时，未确认完成。");
        }
        // Existing files cannot prove this installation succeeded or justify deleting user data.
        Trace($"child exited: code={process.ExitCode};complete={InstallCompletionDetector.IsComplete(dir)}");
        if (process.ExitCode != 0)
            return InstallResult.Fail($"安装程序退出码 {process.ExitCode}。");
        if (!InstallCompletionDetector.IsComplete(dir))
            return InstallResult.Fail("安装未完成：缺少 XCAGI 主程序或后端文件。");
        progress?.Report(new InstallProgressUpdate(100, "安装完成"));
        return InstallResult.Ok(dir, Path.Combine(dir, "XCAGI.exe"));
    }

}

public readonly record struct InstallResult(bool Success, string? InstallDir, string? AppExePath, string? Error)
{
    public static InstallResult Ok(string dir, string? appExe) => new(true, dir, appExe, null);
    public static InstallResult Fail(string error) => new(false, null, null, error);
}
