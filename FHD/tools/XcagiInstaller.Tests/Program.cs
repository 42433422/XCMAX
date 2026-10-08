using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Reflection;
using System.Windows.Threading;
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
var uiPassed = await VerifyCompletionUiAsync();
if (args.Contains("--ui-only")) return uiPassed ? 0 : 1;
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
return uiPassed && results.All(x => (bool)x.GetType().GetProperty("pass")!.GetValue(x)!) ? 0 : 1;

static Task<bool> VerifyCompletionUiAsync()
{
    var outcome = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
    var thread = new Thread(() =>
    {
        SynchronizationContext.SetSynchronizationContext(new DispatcherSynchronizationContext());
        Dispatcher.CurrentDispatcher.BeginInvoke(new Action(async () =>
        {
            try
            {
                var app = new XcagiInstaller.App(); app.InitializeComponent();
                var window = new XcagiInstaller.MainWindow();
                var bar = (System.Windows.Controls.ProgressBar)window.FindName("InstallProgress");
                var label = (System.Windows.Controls.TextBlock)window.FindName("InstallPercentText");
                typeof(XcagiInstaller.MainWindow).GetMethod("UpdateInstallProgress", BindingFlags.NonPublic | BindingFlags.Instance)!.Invoke(window, new object[] { 100.0, "安装完成" });
                var progressPass = bar.Value == 100 && label.Text == "100%";
                var method = typeof(PostInstallTasks).GetMethod("RunAsync");
                var responsive = false; var sta = false; var failureReported = false;
                if (method != null)
                {
                    using var release = new ManualResetEventSlim();
                    var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
                    Func<string> blockingShellWork = () => { sta = Thread.CurrentThread.GetApartmentState() == ApartmentState.STA; entered.SetResult(); if (!release.Wait(5000)) throw new TimeoutException(); return "finished"; };
                    var work = (Task<string>)method.Invoke(null, new object[] { blockingShellWork })!;
                    await entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
                    await Dispatcher.CurrentDispatcher.InvokeAsync(() => { responsive = !work.IsCompleted; release.Set(); });
                    responsive &= await work == "finished";
                    try { await (Task<string>)method.Invoke(null, new object[] { (Func<string>)(() => throw new IOException("shell failure")) })!; }
                    catch (IOException) { failureReported = true; }
                }
                Console.WriteLine(JsonSerializer.Serialize(new { scope = "Actual WPF controls and dispatcher; not customer VM acceptance", progressPass, responsive, sta, failureReported }));
                window.Close(); app.Shutdown(); outcome.SetResult(progressPass && responsive && sta && failureReported);
            }
            catch (Exception ex) { Console.Error.WriteLine(ex); outcome.TrySetResult(false); }
            finally { Dispatcher.CurrentDispatcher.BeginInvokeShutdown(DispatcherPriority.Send); }
        }));
        Dispatcher.Run();
    }) { IsBackground = true };
    thread.SetApartmentState(ApartmentState.STA); thread.Start();
    return AwaitStoppedThreadAsync();
    async Task<bool> AwaitStoppedThreadAsync() { var result = await outcome.Task.WaitAsync(TimeSpan.FromSeconds(30)); await Task.Run(() => thread.Join(5000)); return result; }
}

sealed class InlineProgress(Action<InstallProgressUpdate> report) : IProgress<InstallProgressUpdate>
{
    public void Report(InstallProgressUpdate value) => report(value);
}
