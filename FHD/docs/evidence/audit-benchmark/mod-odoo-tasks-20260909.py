# R22 mod-sdk 域开源锚点实测：Odoo 18 Community 任务集 B1-B3（经 odoo shell 执行）
import json

out = {"benchmark": "odoo", "version": odoo.release.version, "tasks": {}}

env["ir.module.module"].update_list()
env.cr.commit()


def _mod(name):
    return env["ir.module.module"].search([("name", "=", name)], limit=1)


# ---------- B1 模块清单/依赖/生命周期/卸载边界 ----------
try:
    m = _mod("calendar")
    if not m:
        env["ir.module.module"].update_list()
        m = _mod("calendar")
    m.button_immediate_install()
    installed_state = m.state
    # 依赖边界：manifest 声明依赖（calendar 依赖 mail/base），依赖关系可查
    dep_names = [d.name for d in m.dependencies_id]
    has_deps = "mail" in dep_names or "base" in dep_names
    m.button_immediate_uninstall()
    uninstalled_state = m.state
    out["tasks"]["B1"] = {
        "verdict": "PASS" if installed_state == "installed" and uninstalled_state == "uninstalled" and has_deps else "FAIL",
        "install_state": installed_state,
        "uninstall_state": uninstalled_state,
        "dependencies_declared": has_deps,
        "manifest_version": m.latest_version,
        "dependencies": dep_names[:5],
        "mechanism": "manifest 声明依赖；生命周期状态机 installed/uninstalled 可查",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B1"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

# ---------- B2 共享宿主下账号只加载授权模块与数据 ----------
try:
    mp = _mod("product")
    if mp.state != "installed":
        mp.button_immediate_install()
    env.invalidate_all()
    co_a = env["res.company"].search([("name", "=", "R22 Co A")], limit=1) or env["res.company"].create({"name": "R22 Co A"})
    co_b = env["res.company"].search([("name", "=", "R22 Co B")], limit=1) or env["res.company"].create({"name": "R22 Co B"})
    p1 = env["product.product"].search([("name", "=", "R22-A-only")], limit=1) or env["product.product"].create({"name": "R22-A-only", "company_id": co_a.id})
    # 用户仅授权 Co B
    grp_user = env.ref("base.group_user")
    u = env["res.users"].search([("login", "=", "r22_b@bench.test")], limit=1)
    if not u:
        u = env["res.users"].create({
            "name": "R22 User B", "login": "r22_b@bench.test",
            "company_id": co_b.id, "company_ids": [(6, 0, [co_b.id])],
            "groups_id": [(6, 0, [grp_user.id])],
        })
    env.cr.flush()
    env.invalidate_all()
    visible_as_b = env["product.product"].with_user(u.id).with_company(co_b.id).search_count([("id", "=", p1.id)])
    # 直接读也受记录规则保护
    try:
        rec = env["product.product"].with_user(u.id).browse(p1.id).read(["name"])
        direct = "READABLE" if rec else "EMPTY"
    except Exception as e:  # noqa: BLE001
        direct = type(e).__name__
    out["tasks"]["B2"] = {
        "verdict": "PASS" if visible_as_b == 0 and direct != "READABLE" else "FAIL",
        "cross_company_search_visible": visible_as_b,
        "cross_company_direct_read": direct,
        "mechanism": "company_id 记录规则 + 用户 company_ids 授权集；跨公司默认不可见",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B2"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

# ---------- B3 升级保留模块配置，运行版本可查 ----------
try:
    m2 = _mod("survey")
    if m2.state != "installed":
        m2.button_immediate_install()
    env["ir.config_parameter"].sudo().set_param("r22.module_setting", "keep-me")
    m2.button_immediate_upgrade()
    kept = env["ir.config_parameter"].sudo().get_param("r22.module_setting")
    running = _mod("survey")
    version_viewable = bool(running.installed_version or running.latest_version)
    out["tasks"]["B3"] = {
        "verdict": "PASS" if kept == "keep-me" and version_viewable and running.state == "installed" else "FAIL",
        "config_preserved": kept,
        "installed_version": running.installed_version,
        "state": running.state,
        "mechanism": "upgrade 不清配置；ir_module_module 暴露运行版本",
    }
except Exception as e:  # noqa: BLE001
    out["tasks"]["B3"] = {"verdict": "FAIL", "error": f"{type(e).__name__}: {e}"[:300]}

env.cr.commit()
print("RESULT:" + json.dumps(out, ensure_ascii=False, default=str))
