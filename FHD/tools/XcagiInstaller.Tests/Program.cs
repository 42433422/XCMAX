using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Reflection;
using System.Windows.Threading;
using XcagiInstaller.Services;

var upgradeChild = await ManualUpgradeCases.TryRunChildAsync(args);
if (upgradeChild.HasValue) return upgradeChild.Value;
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
var upgradePassed = await ManualUpgradeCases.RunAsync(root);
return uiPassed && upgradePassed && results.All(x => (bool)x.GetType().GetProperty("pass")!.GetValue(x)!) ? 0 : 1;

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
                var wizardPass = VerifyWizardStates(window);
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
                Console.WriteLine(JsonSerializer.Serialize(new { scope = "Actual WPF controls and dispatcher; not customer VM acceptance", progressPass, wizardPass, responsive, sta, failureReported }));
                window.Close(); app.Shutdown(); outcome.SetResult(progressPass && wizardPass && responsive && sta && failureReported);
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

static bool VerifyWizardStates(XcagiInstaller.MainWindow window)
{
    var type = typeof(XcagiInstaller.MainWindow);
    var step = type.GetField("_step", BindingFlags.NonPublic | BindingFlags.Instance)!;
    var apply = type.GetMethod("ApplyStepUi", BindingFlags.NonPublic | BindingFlags.Instance)!;
    var nextHandler = type.GetMethod("Next_OnClick", BindingFlags.NonPublic | BindingFlags.Instance)!;
    var backHandler = type.GetMethod("Back_OnClick", BindingFlags.NonPublic | BindingFlags.Instance)!;
    var welcome = (System.Windows.Controls.Panel)window.FindName("WelcomePanel");
    var license = (System.Windows.Controls.Panel)window.FindName("LicensePanel");
    var directory = (System.Windows.Controls.Panel)window.FindName("DirectoryPanel");
    var installing = (System.Windows.Controls.Panel)window.FindName("InstallingPanel");
    var complete = (System.Windows.Controls.Panel)window.FindName("CompletePanel");
    var error = (System.Windows.Controls.Panel)window.FindName("ErrorPanel");
    var welcomeAgreement = (System.Windows.Controls.CheckBox)window.FindName("WelcomeAgreeCheck");
    var licenseAgreement = (System.Windows.Controls.CheckBox)window.FindName("AgreeLicenseCheck");
    var installDir = (System.Windows.Controls.TextBox)window.FindName("InstallDirBox");
    var next = (System.Windows.Controls.Button)window.FindName("NextButton");
    var back = (System.Windows.Controls.Button)window.FindName("BackButton");
    var cancel = (System.Windows.Controls.Button)window.FindName("CancelButton");
    var dots = Enumerable.Range(1, 5).Select(i => (System.Windows.Shapes.Ellipse)window.FindName("Dot" + i)).ToArray();
    var stepType = step.FieldType;
    void Set(string value) { step.SetValue(window, Enum.Parse(stepType, value)); apply.Invoke(window, null); }
    bool Only(System.Windows.Controls.Panel expected) => new[] { welcome, license, directory, installing, complete, error }.Count(x => x.Visibility == System.Windows.Visibility.Visible) == 1 && expected.Visibility == System.Windows.Visibility.Visible;
    bool ActiveDot(int index) => dots.Select((dot, i) => dot.Width == 7 && dot.Height == 7 && i == index).Count(active => active) == 1;
    var pass = true;

    welcomeAgreement.IsChecked = false;
    licenseAgreement.IsChecked = false;
    Set("Welcome");
    pass &= Only(welcome) && next.Content?.ToString() == "继续" && !next.IsEnabled && back.Visibility == System.Windows.Visibility.Collapsed && cancel.Visibility == System.Windows.Visibility.Visible && ActiveDot(0);
    nextHandler.Invoke(window, new object[] { window, new System.Windows.RoutedEventArgs() });
    pass &= step.GetValue(window)?.ToString() == "Welcome";
    welcomeAgreement.IsChecked = true;
    pass &= licenseAgreement.IsChecked == true && next.IsEnabled;
    nextHandler.Invoke(window, new object[] { window, new System.Windows.RoutedEventArgs() });
    pass &= step.GetValue(window)?.ToString() == "Directory" && Only(directory);

    Set("License");
    licenseAgreement.IsChecked = false;
    apply.Invoke(window, null);
    pass &= Only(license) && next.Content?.ToString() == "继续" && !next.IsEnabled && back.Visibility == System.Windows.Visibility.Visible && cancel.IsEnabled && ActiveDot(1);
    nextHandler.Invoke(window, new object[] { window, new System.Windows.RoutedEventArgs() });
    pass &= step.GetValue(window)?.ToString() == "License";
    licenseAgreement.IsChecked = true;
    pass &= welcomeAgreement.IsChecked == true && next.IsEnabled;
    nextHandler.Invoke(window, new object[] { window, new System.Windows.RoutedEventArgs() });
    pass &= step.GetValue(window)?.ToString() == "Directory" && Only(directory);
    Set("License");
    backHandler.Invoke(window, new object[] { window, new System.Windows.RoutedEventArgs() });
    pass &= step.GetValue(window)?.ToString() == "Welcome" && Only(welcome);

    installDir.Text = " ";
    Set("Directory");
    pass &= Only(directory) && next.Content?.ToString() == "安装" && !next.IsEnabled && back.Visibility == System.Windows.Visibility.Visible && cancel.IsEnabled && ActiveDot(2);
    installDir.Text = @"C:\Synthetic\XCAGI";
    apply.Invoke(window, null);
    pass &= next.IsEnabled;
    backHandler.Invoke(window, new object[] { window, new System.Windows.RoutedEventArgs() });
    pass &= step.GetValue(window)?.ToString() == "Welcome" && Only(welcome);

    Set("Installing");
    pass &= Only(installing) && !next.IsEnabled && back.Visibility == System.Windows.Visibility.Collapsed && cancel.Visibility == System.Windows.Visibility.Visible && !cancel.IsEnabled && ActiveDot(3);
    Set("Complete");
    pass &= Only(complete) && next.Content?.ToString() == "好" && next.IsEnabled && cancel.Visibility == System.Windows.Visibility.Collapsed && ReferenceEquals(next.Style, window.FindResource("SuccessButtonStyle")) && ActiveDot(4);
    Set("Error");
    pass &= Only(error) && next.Content?.ToString() == "好" && next.IsEnabled && cancel.Visibility == System.Windows.Visibility.Collapsed && ReferenceEquals(next.Style, window.FindResource("HeroButtonStyle")) && dots.All(dot => dot.Width == 6 && dot.Height == 6);
    return pass;
}

sealed class InlineProgress(Action<InstallProgressUpdate> report) : IProgress<InstallProgressUpdate>
{
    public void Report(InstallProgressUpdate value) => report(value);
}
