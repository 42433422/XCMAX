using System.Diagnostics;
using System.Text.Json;
using XcagiInstaller.Services;

if (args.Contains("/S"))
{
    var dir = string.Join(" ", args.Skip(1))[3..];
    var mode = Environment.GetEnvironmentVariable("XCMAX_INSTALLER_FIXTURE_MODE");
    if (mode is not ("missing" or "crash-missing")) foreach (var name in new[] { "XCAGI.exe", "resources/app.asar", "resources/backend/xcagi-backend.exe" })
    {
        var file = Path.Combine(dir, name); Directory.CreateDirectory(Path.GetDirectoryName(file)!); File.WriteAllText(file, "fixture");
    }
    if (mode is "slow" or "cancel") await Task.Delay(mode == "slow" ? 7000 : 30000);
    return mode == "failure" ? 7 : mode is "crash" or "crash-missing" ? unchecked((int)0xC0000005) : 0;
}
var root = Path.Combine(Environment.GetEnvironmentVariable("XCMAX_INSTALLER_TEST_ROOT") ?? Path.GetTempPath(), "xcagi-wrapper-" + Guid.NewGuid());
Directory.CreateDirectory(root);
var results = new List<object>();
foreach (var mode in new[] { "success", "failure", "crash", "crash-missing", "missing", "slow", "cancel" })
{
    var dir = Path.Combine(root, mode + " preserved data"); Directory.CreateDirectory(dir);
    var sentinel = Path.Combine(dir, "preserved-customer-data.txt"); File.WriteAllText(sentinel, "unchanged");
    Environment.SetEnvironmentVariable("XCMAX_INSTALLER_FIXTURE_MODE", mode);
    using var cancel = new CancellationTokenSource();
    if (mode == "cancel") cancel.CancelAfter(1200);
    var updates = new List<InstallProgressUpdate>();
    var clock = Stopwatch.StartNew();
    var result = await NsisSilentInstaller.RunAsync(Environment.ProcessPath!, dir, new InlineProgress(updates.Add), cancel.Token);
    var expectedSuccess = mode is "success" or "slow";
    var preserved = File.Exists(sentinel) && File.ReadAllText(sentinel) == "unchanged";
    var completionHonest = expectedSuccess || !updates.Any(x => x.Percent == 100);
    var pass = result.Success == expectedSuccess && preserved && completionHonest && (mode != "slow" || clock.ElapsedMilliseconds >= 7000);
    results.Add(new { mode, pass, result.Success, preserved, completionHonest, elapsedMs = clock.ElapsedMilliseconds });
}
Environment.SetEnvironmentVariable("XCMAX_INSTALLER_FIXTURE_MODE", null);
var json = JsonSerializer.Serialize(new { scope = "Real isolated child-process regression, not installed-product VM acceptance", root, results }, new JsonSerializerOptions { WriteIndented = true });
Console.WriteLine(json);
return results.All(x => (bool)x.GetType().GetProperty("pass")!.GetValue(x)!) ? 0 : 1;

sealed class InlineProgress(Action<InstallProgressUpdate> report) : IProgress<InstallProgressUpdate>
{
    public void Report(InstallProgressUpdate value) => report(value);
}
