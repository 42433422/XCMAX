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
    public static string UserDataDirectory() => Environment.GetEnvironmentVariable("XCAGI_DESKTOP_USER_DATA_DIR")?.Trim() is { Length: > 0 } custom ? custom : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "XCAGI");
    public static void ValidateRegisteredInstallDirectory(string directory)
    {
        foreach (var hive in new[] { Microsoft.Win32.Registry.CurrentUser, Microsoft.Win32.Registry.LocalMachine })
        {
            using var key = hive.OpenSubKey(@"Software\3ec52fbf-5e26-5608-8179-ef89baa3a2c8");
            if (key?.GetValue("InstallLocation") is string old && !string.IsNullOrWhiteSpace(old) && !Path.GetFullPath(old).TrimEnd('\\').Equals(Path.GetFullPath(directory).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase)) throw new IOException("检测到其他目录的旧安装；请在原安装目录更新，以确保失败时可以完整恢复。");
        }
    }

    /// <summary>
    /// 静默运行 NSIS：/S 静默，/D= 必须为最后一个参数且路径勿加引号。
    /// </summary>
    public static async Task<InstallResult> RunAsync(
        string setupExePath,
        string installDirectory,
        IProgress<InstallProgressUpdate>? progress = null,
        CancellationToken cancellationToken = default,
        string? userDataDirectory = null)
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
        WindowsUpgradeSnapshot? snapshot;
        try { snapshot = await Task.Run(() => WindowsUpgradeSnapshot.Prepare(dir, userDataDirectory, cancellationToken), cancellationToken); }
        catch (Exception ex) { return InstallResult.Fail(ex.Message); }
        async Task<InstallResult> FailAfterExit(string error, Process child)
        {
            if (snapshot == null) return InstallResult.Fail(error);
            if (!child.HasExited) return InstallResult.Fail(error + " 安装写入尚未停止，恢复备份已保留。");
            try { await snapshot.RestoreAsync(child.Id); return InstallResult.Fail(error + " 已恢复升级前的程序与数据。"); }
            catch (Exception ex) { return InstallResult.Fail(error + " " + ex.Message); }
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

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromMinutes(30));
        try
        {
            await InstallProgressTracker.MonitorInstallAsync(
                process, dir, progress, timeout.Token).ConfigureAwait(false);
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (Exception ex)
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
            return await FailAfterExit(ex is OperationCanceledException ? cancellationToken.IsCancellationRequested ? "安装已取消。" : "安装超时，未确认完成。" : "安装监控失败：" + ex.Message, process);
        }
        // Existing files cannot prove this installation succeeded or justify deleting user data.
        Trace($"child exited: code={process.ExitCode};complete={InstallCompletionDetector.IsComplete(dir)}");
        if (process.ExitCode != 0)
            return await FailAfterExit($"安装程序退出码 {process.ExitCode}。", process);
        if (!InstallCompletionDetector.IsComplete(dir))
            return await FailAfterExit("安装未完成：缺少 XCAGI 主程序或后端文件。", process);
        progress?.Report(new InstallProgressUpdate(100, "安装完成"));
        return InstallResult.Ok(dir, Path.Combine(dir, "XCAGI.exe")) with { Recovery = snapshot, ExitedInstallerPid = process.Id };
    }

}

public readonly record struct InstallResult(bool Success, string? InstallDir, string? AppExePath, string? Error)
{
    internal WindowsUpgradeSnapshot? Recovery { get; init; }
    internal int ExitedInstallerPid { get; init; }
    internal async Task<string> RecoverPostInstallFailureAsync(string error)
    {
        if (Recovery == null) return error;
        try { await Recovery.RestoreAsync(ExitedInstallerPid); return error + " 已恢复升级前的程序与数据。"; }
        catch (Exception ex) { return error + " " + ex.Message; }
    }
    public static InstallResult Ok(string dir, string? appExe) => new(true, dir, appExe, null);
    public static InstallResult Fail(string error) => new(false, null, null, error);
}
