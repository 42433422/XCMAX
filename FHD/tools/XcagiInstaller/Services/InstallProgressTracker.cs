using System.Diagnostics;
using System.IO;

namespace XcagiInstaller.Services;

/// <summary>
/// 静默 NSIS 无进度回调时，通过安装目录体积与关键文件判断真实进度。
/// </summary>
public static class InstallProgressTracker
{
    // 企业版含 Electron + PyInstaller 后端，解压后常达 800MB～1.5GB
    private const long DefaultEstimatedBytes = 900L * 1024 * 1024;

    public static long EstimateInstalledBytes(string setupExePath, string installDirectory)
    {
        long compressed = 0;
        try
        {
            if (File.Exists(setupExePath))
                compressed = new FileInfo(setupExePath).Length;
        }
        catch
        {
            // ignore
        }

        var baseline = GetDirectorySize(installDirectory);
        // 静默 NSIS 内嵌 Electron + 后端，膨胀倍数高于普通应用
        var fromPayload = compressed > 0 ? (long)(compressed * 3.2) : 0;
        return Math.Max(DefaultEstimatedBytes, Math.Max(baseline + 80_000_000, fromPayload));
    }

    /// <summary>静默 NSIS 解压完毕时关键文件应齐全；进程可能仍挂起。</summary>
    public static bool IsInstallComplete(string installDirectory)
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

    public static async Task<bool> MonitorInstallAsync(
        Process process,
        string installDirectory,
        long estimatedTotalBytes,
        IProgress<InstallProgressUpdate>? progress,
        CancellationToken cancellationToken = default)
    {
        var lastReported = 0;
        var started = Stopwatch.StartNew();
        var expectedMs = EstimateInstallDurationMs(estimatedTotalBytes);
        var targetBytes = Math.Max(estimatedTotalBytes, 1);
        var lastSize = 0L;
        var stagnantLoops = 0;
        var completeStallLoops = 0;
        var hungAfterComplete = false;

        while (!process.HasExited)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var current = GetDirectorySize(installDirectory);
            if (current <= lastSize)
                stagnantLoops++;
            else
            {
                stagnantLoops = 0;
                lastSize = current;
            }

            if (IsInstallComplete(installDirectory))
            {
                completeStallLoops++;
                // 文件已齐全但 NSIS 子进程未退出（常见）：约 5s 后视为完成
                if (completeStallLoops >= 12)
                {
                    hungAfterComplete = true;
                    break;
                }
            }
            else
            {
                completeStallLoops = 0;
            }

            var sizePct = (int)Math.Min(99, current * 100 / targetBytes);
            var timePct = expectedMs > 0
                ? (int)Math.Min(99, started.ElapsedMilliseconds * 100 / expectedMs)
                : 0;

            var blended = Math.Max(sizePct, timePct);

            if (IsInstallComplete(installDirectory))
                blended = Math.Max(blended, 95);
            else if (lastReported >= 75 && stagnantLoops > 8)
            {
                var creep = (int)Math.Min(99, 75 + started.ElapsedMilliseconds / 5000);
                blended = Math.Max(blended, creep);
            }

            var pct = Math.Max(lastReported, Math.Min(99, blended));
            if (pct > lastReported + 3)
                pct = lastReported + 3;

            if (pct != lastReported)
            {
                lastReported = pct;
                progress?.Report(new InstallProgressUpdate(pct, DescribeStage(installDirectory, current, pct, stagnantLoops)));
            }

            await Task.Delay(400, cancellationToken).ConfigureAwait(false);
        }

        progress?.Report(new InstallProgressUpdate(100, "安装完成"));
        return hungAfterComplete;
    }

    private static long EstimateInstallDurationMs(long estimatedTotalBytes)
    {
        // 大体积 + 海量小文件（PyInstaller）；上限 15 分钟
        var fromSize = (long)(estimatedTotalBytes / (4.5 * 1024 * 1024) * 1000);
        return Math.Clamp(fromSize + 20_000, 35_000, 900_000);
    }

    private static string DescribeStage(string installDirectory, long bytesWritten, int percent, int stagnantLoops)
    {
        if (bytesWritten < 5_000_000)
            return "正在初始化安装…";

        var appExe = Path.Combine(installDirectory, "XCAGI.exe");
        if (!File.Exists(appExe))
            return $"正在释放文件… {percent}%";

        var asar = Path.Combine(installDirectory, "resources", "app.asar");
        if (!File.Exists(asar))
            return $"正在部署应用资源… {percent}%";

        if (percent < 85)
            return $"正在部署本地服务与前端… {percent}%";

        if (stagnantLoops > 8)
            return $"正在完成安装与注册（杀毒软件可能拖慢，请耐心等待）… {percent}%";

        return "正在创建快捷方式并完成配置…";
    }

    public static long GetDirectorySize(string path)
    {
        if (!Directory.Exists(path))
            return 0;

        long total = 0;
        try
        {
            foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
            {
                try
                {
                    var info = new FileInfo(file);
                    if (info.Exists)
                        total += info.Length;
                }
                catch
                {
                    // 部分文件可能被 NSIS 占用
                }
            }
        }
        catch
        {
            // ignore
        }

        return total;
    }
}
