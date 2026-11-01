const pick = (pair, language) => pair[language === "en" ? 1 : 0];
function node(tag, className, text) {
  const value = document.createElement(tag);
  if (className) value.className = className;
  if (text !== undefined) value.textContent = text;
  return value;
}

function card(kind, id, title, value, detail, language) {
  const item = node("article", `diagram-node ${kind}-node`);
  item.dataset.node = id;
  item.append(node("span", "node-id", `${id} · ${pick(kind === "data" ? ["数据", "DATA"] : ["处理", "PROCESS"], language)}`),
    node("h4", "", pick(title, language)), node("p", "node-value", value));
  if (detail) {
    const more = node("details", "node-detail");
    more.append(node("summary", "", pick(["工作说明", "How it works"], language)), node("p", "", pick(detail, language)));
    item.append(more);
  }
  return item;
}

function arrow(label, language, branch = false) {
  const edge = node("div", `data-arrow${branch ? " branch-arrow" : ""}`);
  edge.append(node("span", "edge-label", pick(label, language)), node("span", "flow-edge", "→"));
  return edge;
}

function row(items, labels, language) {
  const line = node("div", "diagram-row");
  items.forEach((item, index) => {
    if (index) line.append(arrow(labels[index - 1], language));
    line.append(item);
  });
  return line;
}

export function renderArchitecture(language) {
  const root = document.getElementById("architecture-content");
  const p = pair => pick(pair, language);
  const process = (id, title, value, detail = null) => card("process", id, title, value, detail, language);
  const data = (id, title, value, detail = null) => card("data", id, title, value, detail, language);
  const overview = node("div", "architecture-overview");
  for (const [title, value] of [
    [["触发与恢复", "Trigger & recovery"], "Foundry Routine · Hosted tasks"],
    [["托管编辑核心", "Managed editorial core"], "Microsoft Copilot Harness · GPT-6.1-sol"],
    [["工具与音频服务", "Tools & audio service"], "Hosted · WebIQ · MAI · FFmpeg"],
    [["发布与生命周期", "Publication & lifecycle"], "Blob · HTML / JS / CSS3 · 00:00"],
  ]) {
    const item = node("article", "architecture-component");
    item.append(node("h3", "", p(title)), node("p", "", value));
    overview.append(item);
  }
  const boundary = node("aside", "architecture-boundary");
  boundary.append(node("h3", "", p(["Microsoft Copilot Harness 是编辑执行核心，不是语音服务", "Microsoft Copilot Harness is the editorial runtime, not the speech service"])),
    node("p", "", p(["独立托管 Prompt Agent：microsoft_copilot_preview。它实际执行内置 subagents、Shell 与文件工具；Hosted Agent 保留定时任务恢复、WebIQ 工具回传、校验、MAI 合成和 Blob 发布。下图是数据契约示意，不是实时遥测；节目必须有真实执行记录，才标记为托管制作。", "A separate managed Prompt Agent uses microsoft_copilot_preview and actually executes native subagents, shell and file tools. The Hosted Agent retains task recovery, WebIQ tool transport, validation, MAI synthesis and Blob publication. This diagram shows data contracts, not live telemetry; only verified runtime records qualify a bulletin as managed production."])));
  const reference = node("a", "architecture-reference", p(["Microsoft 官方公告 ↗", "Microsoft announcement ↗"]));
  reference.href = "https://devblogs.microsoft.com/foundry/microsoft-copilot-harness-in-foundry/";
  reference.target = "_blank";reference.rel = "noopener noreferrer";boundary.append(reference);
  const heading = node("div", "dataflow-heading");
  const title = node("h3", "", p(["应用执行数据节点图", "Application execution data-node diagram"]));
  title.id = "architecture-flow-title";
  const pause = node("button", "flow-toggle");
  pause.type = "button";pause.setAttribute("aria-controls", "architecture-flow");
  const update = () => {
    const paused = root.classList.contains("flow-paused");
    pause.textContent = p(paused ? ["继续流动示意", "Resume flow animation"] : ["暂停流动示意", "Pause flow animation"]);
    pause.setAttribute("aria-pressed", String(paused));
  };
  pause.addEventListener("click", () => {root.classList.toggle("flow-paused");update();});update();
  heading.append(title, pause);
  const legend = node("p", "flow-legend", p(["P = 执行节点 · D = 实际数据节点 · 箭头标注传递内容 · 虚线 = 资料不足时补搜。点开「工作说明」查看处理职责。", "P = process · D = actual data · labelled arrows = transferred payload · dashed route = missing-detail research. Expand “How it works” for responsibilities."]));
  const flow = node("div", "dataflow-diagram");
  flow.id = "architecture-flow";flow.setAttribute("aria-labelledby", title.id);
  flow.append(row([
    process("P01", ["定时触发", "Scheduled trigger"], ":00 / :30 · Asia/Shanghai", ["每半小时调用；手动加更由服务器取当前分钟。", "Invoke every half hour; manual extras use the server's current minute."]),
    data("D01", ["任务输入", "Task input"], "slot · invocation_id"),
    process("P02", ["Hosted 恢复与采集桥接", "Hosted recovery & discovery bridge"], "task ID · Blob lease · collect_news", ["按时段幂等与检查点恢复；调用托管 Microsoft Copilot Harness，再执行其 collect_news 请求。WebIQ 搜索新华社、AP、AFP、Bloomberg，结果通过 function_call_output 返回原会话。密钥留在服务器。", "Resume per-slot checkpoints under a lease. Call the managed Microsoft Copilot Harness and execute its collect_news request. WebIQ searches Xinhua, AP, AFP and Bloomberg; function_call_output returns results to the same conversation. Keys stay on the server."]),
    data("D02", ["公开报道证据包", "Public-report evidence"], "evidence.json · ID / URL / date / facts"),
  ], [["任务参数", "Task parameters"], ["创建 / 恢复", "Start / resume"], ["去重与时效检查", "Deduplicate / check dates"]], language));
  flow.append(arrow(["D02 证据包 → 托管编辑会话", "D02 evidence → managed editorial conversation"], language));
  const harness = node("section", "harness-runtime");
  harness.append(node("h3", "", p(["Foundry 托管 Microsoft Copilot Harness 执行边界", "Foundry-managed Microsoft Copilot Harness execution boundary"])),
    process("P03", ["主编辑 / 调度器", "Parent editor / coordinator"], "GPT-6.1-sol · Responses API · native task", ["各编辑阶段创建隔离会话，按需要有界委派最多三个子任务；主编辑负责合并结果与确定下一步，不另外部署三个常驻 agent。下面说明的是逻辑职责，不保证每次都固定创建三个相同子任务。", "Each editorial phase gets an isolated conversation and up to three bounded tasks as needed. The parent merges results and decides the next step; these are logical responsibilities, not three separately deployed agents or an identical fixed trio on every call."]),
    arrow(["分发 D02 / 补搜证据 + 阶段任务 → native subagents", "Dispatch D02 / expanded evidence + phase tasks → native subagents"], language));
  const roles = node("div", "native-roles");
  for (const [id, title, input, work, output] of [
    ["P04", ["国内研究 subagent", "China research subagent"], "China evidence + topic IDs", ["合并同一事件；提取有引用的事实，列出资料缺口与补搜查询；不以评论补齐内容。", "Merge related China reports, extract cited facts and list missing details / focused queries. Never fill gaps with opinion."], "domestic topics · facts · gaps"],
    ["P05", ["国际研究 subagent", "World research subagent"], "World evidence + agency coverage", ["整理跨社报道和主题顺序；识别 AP / AFP / Bloomberg 等稀缺来源，输出可补搜主题。", "Organize cross-agency reports and topic order, identify sparse AP / AFP / Bloomberg coverage and propose focused research."], "international topics · citations · gaps"],
    ["P06", ["事实核验 subagent", "Fact-verification subagent"], "Expanded evidence + briefs / scripts", ["核对证据 ID、来源时间、主题事实和中英一致性；反馈冲突、缺证据与不可用主题，交由主编辑修订。", "Check evidence IDs, source dates, topic facts and bilingual consistency; return conflicts, missing support and unusable topics for the parent to revise."], "verified facts · citation checks · issues"],
  ]) {
    const role = node("article", "native-role");
    role.append(node("p", "agent-port", `IN · ${input}`),
      process(id, title, "native task · read_agent (when asynchronous)", work),
      node("p", "agent-port agent-output", `OUT · ${output}`));
    role.querySelector("details").open = true;
    roles.append(role);
  }
  harness.append(roles, arrow(["子任务结果 → 主编辑合并 / 检查", "Subtask results → parent merge / check"], language));
  const loop = node("aside", "flow-branch");
  loop.append(node("strong", "", p(["外部 Hosted 工具边界 · 补搜回路", "External Hosted tool boundary · research loop"])),
    node("p", "", p(["P03 委派结果发现缺口 → 越过 Microsoft Copilot Harness 边界调用工具；D04 回传后，P03 再次整理与核验。WebIQ 不在沙箱中执行。", "P03 identifies gaps from delegated results → calls a tool across the Microsoft Copilot Harness boundary. D04 returns to P03 for reorganization and verification. WebIQ does not execute in the sandbox."])), row([
    data("D03", ["主题与资料缺口", "Topics & research gaps"], "topics.json · missing_details · queries"),
    process("P07", ["Microsoft Copilot Harness → Hosted WebIQ 适配器", "Microsoft Copilot Harness → Hosted WebIQ adapter"], "expand_news → function_call_output", ["Hosted 执行定向与稀缺来源补搜，返回同一托管会话。子 agent 不接触 WebIQ 密钥；补搜后再次整理与核验。", "Hosted performs focused and sparse-source searches and returns results to the same managed conversation. Subagents never receive the WebIQ key. Reorganize and verify the expanded package."]),
    data("D04", ["扩展证据 → 回到 P03", "Expanded evidence → back to P03"], "expanded-evidence.json"),
  ], [["缺口查询", "Gap queries"], ["新证据回传 ↺", "Return new evidence ↺"]], language));
  const sandbox = node("div", "sandbox-boundary");
  sandbox.append(process("P08", ["隔离沙箱 / 主编辑组装", "Isolated sandbox / parent assembly"], "shell · filesystem_read / write",
    ["主编辑用 Shell 和工作区 JSON 整理证据、检查顺序及引用，先生成中文、再据同一事实改编英文。会话工作区不是永久档案；脚本和真实 task / shell 执行记录回传 Hosted，再存私有 Blob。这里不调用 MAI，也不保存密钥。", "The parent uses shell and workspace JSON to organize evidence, check order / citations, then prepare Chinese and a same-facts English adaptation. The workspace is not permanent storage. Scripts and actual task / shell records return to Hosted for private Blob checkpointing. No MAI calls or credentials here."]));
  harness.append(sandbox, arrow(["结构化结果 + 实际工具执行记录 → Hosted 强制校验", "Structured output + actual tool records → mandatory Hosted validation"], language));
  const editorial = node("div", "editorial-zone");
  editorial.append(harness, loop);
  flow.append(editorial);
  flow.append(row([
    data("D05", ["整理结果与审计记录", "Editorial output & runtime records"], "briefs.json · cn|en/script.json · harness/*.json"),
    process("P09", ["Hosted 发布前编辑校验", "Hosted editorial gates"], "Pydantic · source balance · native task / shell", ["核验主题顺序、证据、固定问候与两主持、中英同事实及来源比例；四个编辑阶段必须有真实子任务与 Shell 记录。失败不降级为直接模型。", "Validate topic order, evidence, fixed greetings / two hosts, bilingual facts and agency balance. All four editorial phases require actual task and shell records. No direct-model fallback on failure."]),
    data("D06", ["可合成双语脚本", "Validated bilingual scripts"], "speaker · text · topic_id · evidence_ids"),
  ], [["提交校验", "Submit for validation"], ["通过后交付", "Deliver only after passing"]], language));
  flow.append(arrow(["D06 主持台词 → 服务端语音制作", "D06 anchor turns → server-side speech production"], language));
  flow.append(row([
    process("P10", ["Microsoft MAI Voice 2.1", "Microsoft MAI Voice 2.1"], "CN: Wei / Mei · EN: Grant / Harper", ["逐段合成 PCM；仅 Wei 保音高 1.25x，其余 1.0x。语音密钥仅留在 Hosted。", "Synthesize PCM turns; pitch-preserving 1.25x for Wei only, 1.0x for others. Speech credentials remain in Hosted."]),
    data("D07", ["主持逐段音轨", "Per-anchor audio tracks"], "cn|en/turns/NNN.wav · 24 kHz PCM"),
    process("P11", ["FFprobe / FFmpeg", "FFprobe / FFmpeg"], "timing · loudnorm · AAC / MP4", ["用实际加速后音轨测量新闻起点；拼接与响度归一化。整期及每板块均 ≤20 分钟，超限拒绝发布。", "Measure story starts from processed WAVs; assemble and normalize loudness. Whole programme and each section must be ≤20 minutes; reject oversize output."]),
    data("D08", ["双语音频与新闻时间轴", "Bilingual audio & story timeline"], "cn|en/YYYYMMDD/HHMM.mp4 · chapters / sources"),
  ], [["SSML → PCM", "SSML → PCM"], ["真实时长", "Measured timing"], ["编码与校验", "Encode / validate"]], language));
  flow.append(arrow(["D08 两种语言全部就绪 → 发布租约", "D08 both languages ready → publication lease"], language));
  flow.append(row([
    process("P12", ["Azure Blob 原子发布", "Azure Blob atomic publication"], "private broadcasts · public $web", ["私有保存证据、脚本、WAV、审计；公开保存 MP4。两语言通过校验才更新目录，与跨日清理共用发布租约。", "Keep evidence, scripts, WAVs and audit private; expose MP4s publicly. Commit the catalogue only after both languages pass, under the same lease used by daily cleanup."]),
    data("D09", ["当天公开节目数据", "Today's public programme data"], "media/cn|en/… · catalog.json + manual-catalog.json"),
    process("P13", ["网页播放器与新闻速览", "Web player & headline ticker"], "HTML · JS · CSS3 · 45s refresh", ["默认最新；新闻标题跳转到实测音频位置，来源单独打开。日期时间使用浏览器本地时区。仅循环当天节目，跨日停止旧音频并等待当天首期。", "Default to latest; titles seek to measured audio positions and sources open separately. Display dates in the browser's local zone. Loop only today's audio; stop expired playback and wait for the first new-day bulletin."]),
  ], [["MP4 + 目录 + 定位信息", "MP4 + catalogues + seeking"], ["HTTP / 音频 Range", "HTTP / audio Range"]], language));
  const retention = node("section", "retention-flow");
  retention.append(node("h3", "", p(["跨日数据生命周期", "Midnight data lifecycle"])), row([
    process("P14", ["北京时间 00:00 清理", "00:00 Beijing cleanup"], "Foundry Routine · resilient cleanup", ["独立午夜任务；每次制作也补做清理，覆盖停机遗漏。按 Asia/Shanghai 的节目日期保留当天，旧任务禁止重写已过期内容。", "A dedicated midnight task; each production also sweeps to catch downtime. Retain only today's Asia/Shanghai slots and forbid old jobs from recreating expired content."]),
    data("D10", ["过期数据集合", "Expired data set"], "old catalog entries · cn/en MP4 · jobs/* · invocations"),
    process("P15", ["目录移除 + Blob 删除", "Catalogue removal + Blob deletion"], "publication lease · snapshots included", ["同时清理定时/手动目录、公开和私有音频、原始证据、脚本、WAV 与执行记录。不删除网页静态资源，不等待新一期成功才保留昨天；当天首期未完成时显示等待。", "Prune scheduled/manual catalogues, public/private audio, evidence, scripts, WAVs and runtime records. Preserve static web assets. Do not retain yesterday while waiting for successful new-day production; show a waiting state instead."]),
  ], [["按节目日期筛选", "Select by programme day"], ["删去过期内容", "Delete expired content"]], language));
  retention.append(node("p", "flow-recovery", p(["安全边界：浏览器不接触密钥或原始证据；重要输出保存在私有 Blob，不依赖临时沙箱。存储账号若启用 Azure 软删除，服务仍可能保留不可公开访问的恢复副本；本应用不擅自改变账号级保护配置。", "Security boundary: the browser never sees keys or raw evidence. Durable output uses private Blob, not temporary sandbox state. If Azure soft delete is enabled, non-public recoverable copies may remain; this application does not silently change account-wide protection settings."])));
  flow.append(retention);
  root.replaceChildren(overview, boundary, heading, legend, flow);
}
