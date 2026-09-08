// mods/sunbird-attendance-custom/frontend/src/index.js
async function mount(root, sdk) {
  if (sdk.version !== 1) throw new Error("\u6B64\u6269\u5C55\u9700\u8981\u5BBF\u4E3B SDK v1");
  const node = (tag, text = "") => {
    const value = document.createElement(tag);
    value.textContent = text;
    return value;
  };
  const page = node("section");
  page.style.cssText = "max-width:860px;margin:auto;display:grid;gap:20px;color:var(--text-primary,#172554)";
  const title = node("h1", "\u592A\u9633\u9E1F\u8003\u52E4\u8F6C\u6362");
  const status = node("p", "\u6B63\u5728\u8BFB\u53D6\u5F53\u524D\u8D26\u53F7\u914D\u7F6E\u2026");
  status.setAttribute("role", "status");
  const output = node("div");
  page.append(title, node("p", "\u4F7F\u7528\u5F53\u524D\u8D26\u53F7\u7684\u4EBA\u5458\u540D\u5355\u3001\u6A21\u677F\u4E0E\u73ED\u5236\u89C4\u5219\u751F\u6210\u8003\u52E4\u8868\u3002"), status);
  root.append(page);
  let policy = {};
  const controls = [];
  const action = (label, callback) => {
    const button = node("button", label);
    button.type = "button";
    button.style.cssText = "padding:10px 16px;border:0;border-radius:8px;background:#2563eb;color:white;cursor:pointer";
    button.addEventListener("click", async () => {
      controls.forEach((control) => {
        control.disabled = true;
      });
      try {
        await callback();
      } catch (error) {
        if (!sdk.signal.aborted) status.textContent = error.message || "\u64CD\u4F5C\u5931\u8D25\uFF0C\u8BF7\u91CD\u8BD5";
      } finally {
        controls.forEach((control) => {
          control.disabled = false;
        });
      }
    }, { signal: sdk.signal });
    controls.push(button);
    return button;
  };
  const field = (label, type) => {
    const wrap = node("label", label);
    const input2 = node("input");
    input2.type = type;
    input2.style.cssText = "display:block;margin-top:8px;padding:8px;max-width:100%;border:1px solid #cbd5e1;border-radius:6px";
    wrap.append(input2);
    page.append(wrap);
    return input2;
  };
  const request = async (path, init) => {
    const response = await sdk.request(path, init);
    const body = await response.json();
    if (!response.ok || body.success !== true) throw new Error(typeof body.detail === "string" ? body.detail : body.message || "\u64CD\u4F5C\u672A\u6210\u529F");
    return body;
  };
  const template = field("\u8003\u52E4\u6A21\u677F\uFF08\u542B\u660E\u7EC6\u5DE5\u4F5C\u8868\uFF09", "file");
  template.accept = ".xlsx";
  const replace = field("\u6211\u786E\u8BA4\u66FF\u6362\u5F53\u524D\u8D26\u53F7\u7684\u73B0\u6709\u6A21\u677F", "checkbox");
  page.append(action("\u4FDD\u5B58\u6A21\u677F", async () => {
    if (!template.files?.[0]) throw new Error("\u8BF7\u9009\u62E9\u8003\u52E4\u6A21\u677F");
    const form = new FormData();
    form.append("file", template.files[0]);
    form.append("replace_existing", String(replace.checked));
    await request("/attendance/template", { method: "POST", body: form });
    status.textContent = "\u6A21\u677F\u5DF2\u4FDD\u5B58";
  }));
  const input = field("\u9489\u9489\u8003\u52E4\u6587\u4EF6", "file");
  input.accept = ".xlsx,.xlsm,.xls";
  const month = field("\u8003\u52E4\u6708\u4EFD", "month");
  page.append(action("\u8F6C\u6362\u8003\u52E4\u8868", async () => {
    if (!input.files?.[0]) throw new Error("\u8BF7\u9009\u62E9\u8003\u52E4\u6587\u4EF6");
    status.textContent = "\u6B63\u5728\u8F6C\u6362\u8003\u52E4\u8868\u2026";
    output.replaceChildren();
    const form = new FormData();
    form.append("file", input.files[0]);
    form.append("month", month.value);
    const result = (await request("/attendance/convert-upload", { method: "POST", body: form })).data;
    const path = result.download_path;
    if (typeof path !== "string" || !path.startsWith(`/api/mod/${sdk.modId}/attendance/download?file=output-`)) throw new Error("\u8F6C\u6362\u7ED3\u679C\u7F3A\u5C11\u6709\u6548\u4E0B\u8F7D\u5730\u5740");
    const link = node("a", "\u4E0B\u8F7D\u8F6C\u6362\u540E\u7684\u8003\u52E4\u8868");
    link.href = path;
    link.download = "";
    output.append(link);
    status.textContent = `\u8F6C\u6362\u5B8C\u6210\uFF1A${result.employees_matched} \u4EBA\uFF0C${result.rows_used_for_template} \u6761\u8003\u52E4\u8BB0\u5F55\u3002`;
  }), output);
  page.append(node("h2", "\u8F6C\u6362\u89C4\u5219"));
  const segments = field("\u5DE5\u4F5C\u65E5\u6B63\u73ED\u65F6\u6BB5\uFF08\u9017\u53F7\u5206\u9694\uFF09", "text");
  const keywords = field("\u9002\u7528\u8003\u52E4\u7EC4\uFF08\u9017\u53F7\u5206\u9694\uFF09", "text");
  const sunday = field("\u5468\u65E5\u6309\u52A0\u73ED\u5904\u7406", "checkbox");
  page.append(action("\u4FDD\u5B58\u8F6C\u6362\u89C4\u5219", async () => {
    const value = { ...policy, weekday_segments: segments.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean), company_factory_group_keywords: keywords.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean), sunday_empty_schedule: sunday.checked, sunday_map_sqrt_to_star: sunday.checked };
    policy = (await request("/attendance/policy", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ attendance_policy: value }) })).attendance_policy;
    status.textContent = "\u8F6C\u6362\u89C4\u5219\u5DF2\u4FDD\u5B58";
  }));
  try {
    const result = (await request("/attendance/rules")).data;
    policy = result.attendance_policy || {};
    segments.value = (policy.weekday_segments || ["08:00-12:00", "13:30-17:30"]).join(", ");
    keywords.value = (policy.company_factory_group_keywords || ["\u516C\u53F8-\u8003\u52E4", "\u516C\u53F8\u6B63\u73ED", "\u60E0\u5DDE\u5DE5\u5382-\u6B63\u73ED", "\u5DE5\u5382\u6B63\u73ED"]).join(", ");
    sunday.checked = policy.sunday_empty_schedule !== false;
    status.textContent = `\u5F53\u524D\u8D26\u53F7\u4EBA\u5458 ${result.roster_count} \u4EBA\uFF1B${result.template_ready ? "\u6A21\u677F\u5DF2\u5C31\u7EEA" : "\u8BF7\u5148\u4FDD\u5B58\u6216\u5B89\u88C5\u8003\u52E4\u6A21\u677F"}\u3002`;
  } catch (error) {
    if (!sdk.signal.aborted) status.textContent = error.message;
  }
  return () => page.remove();
}
export {
  mount
};
