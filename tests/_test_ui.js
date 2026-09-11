/* 用 jsdom 真跑一遍配置面板：验证渲染、增删时间点、通道开关与「收集→回填→再收集」往返一致 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const UI = require("path").join(__dirname, "..", "ui.html");
const html = fs.readFileSync(UI, "utf8");

const SAMPLE = {
  running: false, elapsed: 0, last_run: "", last_result: "", next_schedule: "",
  mumu: "未知", adb: "未知", maa: "未运行", task: "—", server: "http://127.0.0.1:17800",
  phases: {},
  config_summary: {
    platform: "windows", platform_label: "Windows",
    vm_index: 0, adb_address: "", ready_timeout: 180, shutdown_after_complete: true,
    close_manager: true,
    mumu_cli: "C:\\Program Files\\Netease\\MuMu\\nx_main\\mumu-cli.exe",
    mumu_adb: "C:\\Program Files\\Netease\\MuMu\\nx_main\\adb.exe",
    maa_exe: "C:\\MAA\\MAA.exe", maa_profile: "挂机流水线",
    maa_backend: "gui", maa_cli_config_dir: "",
    maa_close_after_complete: true, maa_close_delay: 10,
    accounts: [
      {name: "官服主号", account_name: "4567", enabled: true},
      {name: "B服小号", account_name: "张三", enabled: false}
    ],
    schedule: { enabled: true, times: ["08:00", "20:00"], days: [0, 1, 2, 3, 4, 5], only_if_idle: true },
    notify: {
      desktop: true,
      email: { enabled: true, smtp_host: "smtp.qq.com", smtp_port: 465, use_ssl: true,
               username: "me@qq.com", password: "authcode", to: "me@qq.com" },
      serverchan: { enabled: true, sendkey: "SCT123" },
      pushplus: { enabled: false, token: "", topic: "" },
      wxpusher: { enabled: false, app_token: "", uids: "" },
      qmsg: { enabled: true, key: "qmsgkey", qq: "10001", type: "group" },
      webhook: { enabled: false, url: "", format: "通用 JSON" }
    },
    port: 17800
  }
};

const calls = [];
const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  beforeParse(window) {
    window.fetch = (url, opt) => {
      calls.push({ url: String(url), body: opt && opt.body });
      const payload = String(url).includes("/api/state") ? SAMPLE : { ok: true, msg: "stub" };
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    };
    window.EventSource = class { constructor() {} close() {} };
  }
});

const errors = [];
dom.window.addEventListener("error", e => errors.push(String(e.message)));

setTimeout(() => {
  const win = dom.window, doc = win.document;
  const fail = [];
  const ok = (cond, label, extra) => {
    console.log((cond ? "  [OK] " : "  [!!] ") + label + (cond ? "" : "  → " + JSON.stringify(extra)));
    if (!cond) fail.push(label);
  };

  console.log("=== 页面脚本错误 ===");
  console.log(errors.length ? errors.join("\n") : "  无");

  console.log("=== 1. 面板渲染 ===");
  const rows = doc.querySelectorAll("#times input[type=time]");
  ok(rows.length === 2, "渲染出 2 个时间点输入框", Array.from(rows).map(r => r.value));
  ok(Array.from(rows).map(r => r.value).join(",") === "08:00,20:00", "时间点值正确（含排序）");
  ok(doc.querySelectorAll(".chan").length === 6, "渲染出 6 个通知通道",
     doc.querySelectorAll(".chan").length);
  ok(doc.querySelector('.c-chon[data-ch="serverchan"]').checked === true, "Server酱 勾选状态正确");
  ok(doc.getElementById("body-serverchan").className.indexOf("off") === -1, "已启用通道展开");
  ok(doc.getElementById("body-pushplus").className.indexOf("off") !== -1, "未启用通道收起");
  ok(doc.getElementById("c-email-smtp_host").value === "smtp.qq.com", "邮件字段回填正确");
  ok(doc.getElementById("c-qmsg-type").value === "group", "Qmsg 发送方式回填正确");
  ok(doc.getElementById("c-webhook-format").value === "通用 JSON", "Webhook 格式回填正确");
  ok(!!doc.getElementById("c-cli-dir"), "渲染 maa-cli 配置目录字段");

  console.log("=== 2. 增删时间点 ===");
  doc.getElementById("btn-add-time").click();
  ok(doc.querySelectorAll("#times input[type=time]").length === 3, "添加后 3 行");
  const newRow = doc.querySelectorAll(".timerow")[2];
  newRow.querySelector("input").value = "23:30";
  newRow.querySelector("button").click();
  ok(doc.querySelectorAll("#times input[type=time]").length === 2, "删除后回到 2 行");

  console.log("=== 3. 通道开关显隐 ===");
  const box = doc.querySelector('.c-chon[data-ch="pushplus"]');
  box.checked = true;
  box.onchange();
  ok(doc.getElementById("body-pushplus").className.indexOf("off") === -1, "勾选后展开字段");
  doc.getElementById("c-pushplus-token").value = "tok-abc";

  console.log("=== 4. collectCfg 收集结果 ===");
  const out = win.collectCfg();
  ok(out.schedule.times.join(",") === "08:00,20:00", "times 收集正确", out.schedule.times);
  ok(out.schedule.enabled === true && out.schedule.only_if_idle === true, "定时开关收集正确");
  ok(out.schedule.days.join(",") === "0,1,2,3,4,5", "生效日期收集正确", out.schedule.days);
  ok(out.notify.desktop === true, "桌面通知收集正确");
  ok(out.notify.serverchan.sendkey === "SCT123" && out.notify.serverchan.enabled === true, "Server酱");
  ok(out.notify.pushplus.token === "tok-abc" && out.notify.pushplus.enabled === true, "PushPlus 新填内容被收集");
  ok(out.notify.email.password === "authcode" && out.notify.email.enabled === true, "邮件授权码保留（不会被清空）");
  ok(out.notify.email.smtp_port === 465 && out.notify.email.use_ssl === true, "邮件端口与加密方式");
  ok(out.notify.qmsg.type === "group" && out.notify.webhook.format === "通用 JSON", "下拉字段收集正确");
  ok(out.notify.webhook.url === "" && out.notify.webhook.enabled === false, "未启用通道保持关闭");
  ok(out.mumu.close_manager === true, "关闭 MuMu 管理器开关收集正确");
  ok(out.maa.close_after_complete === true && out.maa.close_delay === 10,
     "MAA 完成后自动关闭与其延迟收集正确", out.maa);
  ok(Array.isArray(out.maa.accounts) && out.maa.accounts.length === 2, "收集到 2 个账号", out.maa.accounts);
  ok(out.maa.accounts[0].name === "官服主号" && out.maa.accounts[0].account_name === "4567" && out.maa.accounts[0].enabled === true,
     "第一个账号字段正确", out.maa.accounts[0]);
  ok(out.maa.accounts[1].enabled === false && out.maa.accounts[1].account_name === "张三",
     "停用账号也会被保存（只是不跑）", out.maa.accounts[1]);

  console.log("=== 2b. 增删与调序账号 ===");
  doc.getElementById("btn-add-acc").click();
  ok(doc.querySelectorAll(".accrow").length === 3, "添加后 3 行账号");
  const newAcc = doc.querySelectorAll(".accrow")[2];
  newAcc.querySelector(".acc-name").value = "第三号";
  newAcc.querySelector(".acc-frag").value = "8901";
  newAcc.querySelector(".acc-up").click();
  const mid = win.collectCfg().maa.accounts;
  ok(mid[1].name === "第三号" && mid[2].name === "B服小号", "上移后顺序正确", mid);
  newAcc.querySelector(".acc-del").click();
  ok(doc.querySelectorAll(".accrow").length === 2, "删除后回到 2 行");

  console.log("=== 5. 往返一致性：收集 → 回填 → 再收集 ===");
  const round = JSON.parse(JSON.stringify(out));
  round.vm_index = out.mumu.vm_index;
  round.mumu_cli = out.mumu.cli;
  round.mumu_adb = out.mumu.adb;
  round.adb_address = out.mumu.adb_address;
  round.ready_timeout = out.mumu.ready_timeout;
  round.shutdown_after_complete = out.mumu.shutdown_after_complete;
  round.close_manager = out.mumu.close_manager;
  round.maa_exe = out.maa.exe;
  round.maa_profile = out.maa.profile;
  round.maa_cli_config_dir = out.maa.cli_config_dir;
  round.maa_close_after_complete = out.maa.close_after_complete;
  round.maa_close_delay = out.maa.close_delay;
  round.accounts = out.maa.accounts;
  win.buildCfg(round, out.schedule, out.notify);
  const again = win.collectCfg();
  const same = JSON.stringify(again) === JSON.stringify(out);
  ok(same, "二次收集与首次完全一致（保存不会丢配置）");
  if (!same) {
    console.log("   首次:", JSON.stringify(out));
    console.log("   二次:", JSON.stringify(again));
  }

  console.log("=== 6. 单通道「发送测试」按钮 ===");
  calls.length = 0;
  doc.querySelector('.tbtn[data-ch="qmsg"]').click();
  setTimeout(() => {
    const call = calls.filter(c => c.url.includes("/api/notify-test"))[0];
    ok(!!call, "点了测试按钮会调用后端");
    if (call) {
      const body = JSON.parse(call.body);
      ok(body.channel === "qmsg", "带上了通道标识", body.channel);
      ok(body.config && body.config.notify && body.config.notify.qmsg.key === "qmsgkey",
         "带着界面当前填写的内容去测（无需先保存）");
    }
    console.log();
    console.log(fail.length ? ("存在未通过项：" + fail.join(" / ")) : "全部通过");
    process.exit(fail.length ? 1 : 0);
  }, 60);
}, 120);
