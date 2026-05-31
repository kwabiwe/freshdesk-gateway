import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Building2,
  Check,
  ChevronRight,
  ClipboardCheck,
  FileClock,
  FilePlus2,
  Files,
  Gauge,
  History,
  LayoutDashboard,
  ListChecks,
  Octagon,
  RefreshCw,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  Ticket,
  Users,
  X,
} from "lucide-react";

const API = "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : body.detail?.message || JSON.stringify(body.detail);
    } catch {
      // Keep the HTTP status when the body is not JSON.
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

const navigation = [
  ["dashboard", "Dashboard", LayoutDashboard],
  ["new", "New ticket", FilePlus2],
  ["change", "Change-style ticket", ClipboardCheck],
  ["batch", "Batch tickets", Files],
  ["schema", "Freshdesk schema", ListChecks],
  ["related", "Related tickets", Search],
  ["audit", "Audit log", History],
  ["settings", "Settings & help", SettingsIcon],
];

function cls(...parts) {
  return parts.filter(Boolean).join(" ");
}

function choiceValues(choices) {
  if (Array.isArray(choices)) return choices;
  if (choices && typeof choices === "object") return Object.keys(choices);
  return [];
}

function formatDate(value) {
  if (!value) return "Not yet synced";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function mergeBlankDefaults(form, defaults) {
  const merged = { ...form };
  Object.entries(defaults || {}).forEach(([key, value]) => {
    if (key !== "identity" && value != null && (merged[key] == null || merged[key] === "")) merged[key] = value;
  });
  merged.custom_fields = { ...(defaults?.custom_fields || {}), ...(form.custom_fields || {}) };
  return merged;
}

function Field({ label, hint, children, span = false }) {
  return (
    <label className={cls("field", span && "field-span")}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

function Button({ children, icon: Icon, variant = "default", className, ...props }) {
  return (
    <button className={cls("button", `button-${variant}`, className)} {...props}>
      {Icon && <Icon size={16} strokeWidth={2} />}
      <span>{children}</span>
    </button>
  );
}

function Badge({ children, tone = "neutral" }) {
  return <span className={cls("badge", `badge-${tone}`)}>{children}</span>;
}

function Empty({ title, text }) {
  return (
    <div className="empty">
      <p>{title}</p>
      {text && <span>{text}</span>}
    </div>
  );
}

function Modal({ title, copy, confirmWord, actionLabel, danger = false, onClose, onConfirm }) {
  const [typed, setTyped] = useState("");
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="Close">
          <X size={18} />
        </button>
        <h2>{title}</h2>
        <p>{copy}</p>
        <Field label={`Type ${confirmWord} to confirm`}>
          <input autoFocus value={typed} onChange={(event) => setTyped(event.target.value)} />
        </Field>
        <div className="modal-actions">
          <Button type="button" variant="quiet" onClick={onClose}>Cancel</Button>
          <Button type="button" variant={danger ? "danger" : "dark"} disabled={typed !== confirmWord} onClick={() => onConfirm(typed)}>
            {actionLabel}
          </Button>
        </div>
      </section>
    </div>
  );
}

function App() {
  const [page, setPage] = useState("dashboard");
  const [composerForms, setComposerForms] = useState({
    generic: { ...initialTicket },
    change: { ...initialTicket },
  });
  const [composerDrafts, setComposerDrafts] = useState({ generic: null, change: null });
  const [composerAssumptions, setComposerAssumptions] = useState({ generic: [], change: [] });
  const [batchWorkspace, setBatchWorkspace] = useState({
    text: "",
    baseSubject: "New user request",
    baseDescription: "Please process the following new user request.",
    batch: null,
    selected: [],
  });
  const [status, setStatus] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [audit, setAudit] = useState([]);
  const [schema, setSchema] = useState(null);
  const [notice, setNotice] = useState(null);
  const [modal, setModal] = useState(null);

  const notify = useCallback((type, text) => {
    setNotice({ type, text });
    window.setTimeout(() => setNotice(null), 5000);
  }, []);

  const refresh = useCallback(async () => {
    const [statusData, auditData] = await Promise.all([request("/status"), request("/audit?limit=12")]);
    setStatus(statusData);
    setAudit(auditData);
    if (!statusData.emergency_stop.active) {
      const [draftData, schemaData, genericDefaults, changeDefaults] = await Promise.all([
        request("/tickets/drafts"),
        request("/freshdesk/schema"),
        request("/tickets/defaults?kind=generic"),
        request("/tickets/defaults?kind=change"),
      ]);
      setDrafts(draftData);
      setSchema(schemaData);
      setComposerForms((current) => ({
        generic: mergeBlankDefaults(current.generic, genericDefaults),
        change: mergeBlankDefaults(current.change, changeDefaults),
      }));
    }
  }, []);

  useEffect(() => {
    refresh().catch((error) => notify("error", error.message));
  }, [refresh, notify]);

  const performEmergencyAction = async (action, confirmation) => {
    try {
      await request(action === "stop" ? "/admin/emergency-stop" : "/admin/resume", {
        method: "POST",
        body: JSON.stringify({ confirmation }),
      });
      setModal(null);
      await refresh();
      notify("success", action === "stop" ? "Emergency stop is active." : "Gateway resumed.");
    } catch (error) {
      notify("error", error.message);
    }
  };

  const activePage = status?.emergency_stop.active && !["dashboard", "audit", "settings"].includes(page) ? "dashboard" : page;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">FG</div>
          <div>
            <strong>Freshdesk</strong>
            <span>Local gateway</span>
          </div>
        </div>
        <nav>
          {navigation.map(([id, label, Icon]) => (
            <button
              type="button"
              key={id}
              className={cls("nav-item", activePage === id && "nav-item-active")}
              onClick={() => setPage(id)}
            >
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <ShieldCheck size={17} />
          <span>Credentials stay in the backend</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <span className="eyebrow">Local-only ticket creation</span>
            <h1>{navigation.find(([id]) => id === activePage)?.[1]}</h1>
          </div>
          <Button
            variant={status?.emergency_stop.active ? "dark" : "danger"}
            icon={Octagon}
            onClick={() =>
              setModal({
                kind: status?.emergency_stop.active ? "resume" : "stop",
              })
            }
          >
            {status?.emergency_stop.active ? "Resume gateway" : "Emergency stop"}
          </Button>
        </header>

        {status?.emergency_stop.active && (
          <div className="stop-banner">
            <Octagon size={22} />
            <div>
              <strong>Emergency stop active</strong>
              <span>Freshdesk reads, writes, searches, schema sync, and ticket workflows are blocked.</span>
            </div>
          </div>
        )}

        <div className="content">
          {activePage === "dashboard" && (
            <Dashboard status={status} drafts={drafts} audit={audit} setPage={setPage} refresh={refresh} notify={notify} />
          )}
          {activePage === "new" && (
            <TicketComposer
              kind="generic"
              schema={schema}
              refresh={refresh}
              notify={notify}
              setModal={setModal}
              form={composerForms.generic}
              draft={composerDrafts.generic}
              assumptions={composerAssumptions.generic}
              setAssumptions={(assumptions) => setComposerAssumptions((current) => ({ ...current, generic: assumptions }))}
              setDraft={(draft) => setComposerDrafts((current) => ({ ...current, generic: draft }))}
              setForm={(updater) => setComposerForms((current) => ({
                ...current,
                generic: typeof updater === "function" ? updater(current.generic) : updater,
              }))}
            />
          )}
          {activePage === "change" && (
            <TicketComposer
              kind="change"
              schema={schema}
              refresh={refresh}
              notify={notify}
              setModal={setModal}
              form={composerForms.change}
              draft={composerDrafts.change}
              assumptions={composerAssumptions.change}
              setAssumptions={(assumptions) => setComposerAssumptions((current) => ({ ...current, change: assumptions }))}
              setDraft={(draft) => setComposerDrafts((current) => ({ ...current, change: draft }))}
              setForm={(updater) => setComposerForms((current) => ({
                ...current,
                change: typeof updater === "function" ? updater(current.change) : updater,
              }))}
            />
          )}
          {activePage === "batch" && <BatchTickets refresh={refresh} notify={notify} setModal={setModal} workspace={batchWorkspace} setWorkspace={setBatchWorkspace} />}
          {activePage === "schema" && <SchemaPage schema={schema} setSchema={setSchema} refresh={refresh} notify={notify} />}
          {activePage === "related" && <RelatedTickets notify={notify} />}
          {activePage === "audit" && <AuditPage audit={audit} setAudit={setAudit} notify={notify} />}
          {activePage === "settings" && <SettingsPage notify={notify} refresh={refresh} />}
        </div>
      </main>

      {notice && (
        <div className={cls("notice", `notice-${notice.type}`)}>
          {notice.type === "error" ? <AlertTriangle size={17} /> : <Check size={17} />}
          <span>{notice.text}</span>
        </div>
      )}

      {modal?.kind === "stop" && (
        <Modal
          title="Activate emergency stop?"
          copy="This immediately blocks all Freshdesk reads and writes. You can also activate it from Terminal by creating the STOP file."
          confirmWord="STOP"
          actionLabel="Activate stop"
          danger
          onClose={() => setModal(null)}
          onConfirm={(word) => performEmergencyAction("stop", word)}
        />
      )}
      {modal?.kind === "resume" && (
        <Modal
          title="Resume Freshdesk access?"
          copy="Freshdesk operations become available again. Local rate limits remain in effect."
          confirmWord="RESUME"
          actionLabel="Resume gateway"
          onClose={() => setModal(null)}
          onConfirm={(word) => performEmergencyAction("resume", word)}
        />
      )}
      {modal?.kind === "create" && (
        <Modal
          title="Create this Freshdesk ticket?"
          copy={`Review complete. This sends the exact approved draft to Freshdesk as your named account: ${modal.subject}`}
          confirmWord="CREATE"
          actionLabel="Create ticket"
          onClose={() => setModal(null)}
          onConfirm={async (word) => {
            try {
              await request(`/tickets/drafts/${modal.draftId}/approve-create`, {
                method: "POST",
                body: JSON.stringify({ confirmation: word }),
              });
              setModal(null);
              await refresh();
              notify("success", "Freshdesk ticket created.");
            } catch (error) {
              notify("error", error.message);
            }
          }}
        />
      )}
      {modal?.kind === "batch" && (
        <Modal
          title="Create selected Freshdesk tickets?"
          copy={`This sends ${modal.draftIds.length} reviewed drafts to Freshdesk. Each ticket counts as one write action.`}
          confirmWord="CREATE BATCH"
          actionLabel="Create selected"
          onClose={() => setModal(null)}
          onConfirm={async (word) => {
            try {
              await request(`/tickets/batch/${modal.batchId}/approve-create`, {
                method: "POST",
                body: JSON.stringify({ confirmation: word, draft_ids: modal.draftIds }),
              });
              setModal(null);
              await refresh();
              notify("success", "Selected Freshdesk tickets created.");
            } catch (error) {
              notify("error", error.message);
            }
          }}
        />
      )}
    </div>
  );
}

function Dashboard({ status, drafts, audit, setPage, refresh, notify }) {
  const rate = status?.rate_limit || {};
  const recentDrafts = drafts.slice(0, 4);
  const syncSchema = async () => {
    try {
      await request("/freshdesk/sync-schema", { method: "POST" });
      await refresh();
      notify("success", "Freshdesk schema synced.");
    } catch (error) {
      notify("error", error.message);
    }
  };

  return (
    <>
      <section className="dashboard-grid">
        <article className="metric metric-wide">
          <span className="metric-label">Writes remaining this hour</span>
          <strong className="metric-number">{rate.writes_remaining ?? "—"}</strong>
          <span className="metric-note">of {rate.writes_limit ?? "—"} local write actions</span>
        </article>
        <StatusCard label="Freshdesk" value={status?.freshdesk.connected ? "Connected" : status?.freshdesk.configured ? "Configured, not tested" : "Not configured"} icon={Ticket} />
        <StatusCard label="Local model" value={status?.local_llm.connected ? "Connected" : "Not tested"} icon={Sparkles} />
        <StatusCard
          label="Emergency stop"
          value={status?.emergency_stop.active ? "Armed" : "Normal"}
          icon={Octagon}
          alert={status?.emergency_stop.active}
        />
        <StatusCard label="Drafts awaiting approval" value={status?.drafts_awaiting_approval ?? "—"} icon={FileClock} />
        <article className="metric metric-sync">
          <span className="metric-label">Last schema sync</span>
          <strong>{formatDate(status?.schema.last_sync)}</strong>
          <Button icon={RefreshCw} variant="quiet" onClick={syncSchema} disabled={status?.emergency_stop.active}>
            Sync now
          </Button>
        </article>
      </section>

      <section className="section">
        <div className="section-head">
          <div>
            <span className="eyebrow">Start a workflow</span>
            <h2>Primary actions</h2>
          </div>
        </div>
        <div className="action-grid">
          <ActionCard icon={FilePlus2} title="New ticket" text="Draft a standard Freshdesk ticket from rough notes." onClick={() => setPage("new")} />
          <ActionCard icon={ClipboardCheck} title="Change-style ticket" text="Structure a normal ticket with change-request sections." onClick={() => setPage("change")} />
          <ActionCard icon={Files} title="Batch tickets" text="Create one reviewed draft per pasted table row." onClick={() => setPage("batch")} />
          <ActionCard icon={Search} title="Related tickets" text="Find tickets connected to your configured identity." onClick={() => setPage("related")} />
        </div>
      </section>

      <section className="split">
        <div className="section">
          <div className="section-head">
            <h2>Recent drafts</h2>
            <Button variant="text" onClick={() => setPage("new")}>New draft</Button>
          </div>
          {recentDrafts.length ? recentDrafts.map((draft) => <DraftLine key={draft.draft_id} draft={draft} />) : <Empty title="No drafts yet" text="Start with a new ticket or change-style ticket." />}
        </div>
        <div className="section">
          <div className="section-head">
            <h2>Recent audit events</h2>
            <Button variant="text" onClick={() => setPage("audit")}>View all</Button>
          </div>
          {audit.slice(0, 5).map((event) => <AuditLine key={event.id} event={event} />)}
        </div>
      </section>
    </>
  );
}

function StatusCard({ label, value, icon: Icon, alert }) {
  return (
    <article className={cls("metric", alert && "metric-alert")}>
      <Icon size={18} />
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function ActionCard({ icon: Icon, title, text, onClick }) {
  return (
    <button className="action-card" type="button" onClick={onClick}>
      <Icon size={22} />
      <strong>{title}</strong>
      <span>{text}</span>
      <ChevronRight className="action-arrow" size={18} />
    </button>
  );
}

const initialTicket = {
  subject: "",
  description: "",
  rough_notes: "",
  requester_email: "",
  requester_name: "",
  group_id: "",
  company_id: "",
  priority: 1,
  status: 2,
  source: 2,
  type: "",
  custom_fields: {},
  change_document: null,
  assumptions: [],
  skill_version: "",
};

function textLines(value) {
  return (value || "").split("\n").map((line) => line.trim()).filter(Boolean);
}

function configurationItemLines(items) {
  return (items || []).map((item) => [item.name, item.site_location, item.purpose].join(" | ")).join("\n");
}

function rollbackLines(branches) {
  return (branches || []).flatMap((branch) => (branch.steps || []).map((step) => `${branch.scenario || "Rollback"} | ${step}`)).join("\n");
}

function parseConfigurationItems(value) {
  return textLines(value).map((line) => {
    const [name = "TBD", site_location = "", purpose = ""] = line.split("|").map((item) => item.trim());
    return { name, site_location, purpose };
  });
}

function parseRollbackBranches(value) {
  const branches = [];
  textLines(value).forEach((line) => {
    const [scenario = "Rollback", ...stepParts] = line.split("|").map((item) => item.trim());
    const step = stepParts.join(" | ") || scenario;
    const label = stepParts.length ? scenario : "Rollback";
    const existing = branches.find((branch) => branch.scenario === label);
    if (existing) existing.steps.push(step);
    else branches.push({ scenario: label, steps: [step] });
  });
  return branches;
}

function ChangeSectionEditor({ document, setDocument }) {
  if (!document) return null;
  const set = (key, value) => setDocument({ ...document, [key]: value });
  const verification = document.verification || { pre_change: [], in_change: [], post_change: [] };
  const setVerification = (key, value) => set("verification", { ...verification, [key]: textLines(value) });
  return (
    <div className="change-sections">
      <div className="section-head">
        <div><span className="eyebrow">Structured change record</span><h3>Edit generated sections</h3></div>
        <Badge>Live preview</Badge>
      </div>
      <div className="form-grid">
        <Field label="Change title" span><input value={document.title || ""} onChange={(event) => set("title", event.target.value)} /></Field>
        <Field label="Planned change date"><input value={document.planned_change_date || ""} onChange={(event) => set("planned_change_date", event.target.value)} /></Field>
        <Field label="Customer"><input value={document.customer || ""} onChange={(event) => set("customer", event.target.value)} /></Field>
        <Field label="Environment" span><input value={document.environment || ""} onChange={(event) => set("environment", event.target.value)} /></Field>
        <Field label="Background of change" span><textarea rows="5" value={document.background || ""} onChange={(event) => set("background", event.target.value)} /></Field>
        <Field label="Change description" span><textarea rows="5" value={document.change_description || ""} onChange={(event) => set("change_description", event.target.value)} /></Field>
        <Field label="Configuration items" hint="One per line: name | site or location | purpose" span>
          <textarea rows="5" value={configurationItemLines(document.configuration_items)} onChange={(event) => set("configuration_items", parseConfigurationItems(event.target.value))} />
        </Field>
        <Field label="Implementation steps" hint="One ordered step per line" span><textarea rows="8" value={(document.implementation_steps || []).join("\n")} onChange={(event) => set("implementation_steps", textLines(event.target.value))} /></Field>
        <Field label="Rollback branches" hint="One step per line: scenario | rollback action" span><textarea rows="6" value={rollbackLines(document.rollback_branches)} onChange={(event) => set("rollback_branches", parseRollbackBranches(event.target.value))} /></Field>
        <Field label="Pre-change verification"><textarea rows="5" value={verification.pre_change.join("\n")} onChange={(event) => setVerification("pre_change", event.target.value)} /></Field>
        <Field label="In-change verification"><textarea rows="5" value={verification.in_change.join("\n")} onChange={(event) => setVerification("in_change", event.target.value)} /></Field>
        <Field label="Post-change verification" span><textarea rows="5" value={verification.post_change.join("\n")} onChange={(event) => setVerification("post_change", event.target.value)} /></Field>
        <Field label="Risk and impact" span><textarea rows="4" value={document.risk_and_impact || ""} onChange={(event) => set("risk_and_impact", event.target.value)} /></Field>
        <Field label="Expected outcome" span><textarea rows="4" value={document.expected_outcome || ""} onChange={(event) => set("expected_outcome", event.target.value)} /></Field>
        <Field label="Success criteria" hint="One criterion per line" span><textarea rows="5" value={(document.success_criteria || []).join("\n")} onChange={(event) => set("success_criteria", textLines(event.target.value))} /></Field>
        <Field label="Dependencies" hint="One dependency per line" span><textarea rows="4" value={(document.dependencies || []).join("\n")} onChange={(event) => set("dependencies", textLines(event.target.value))} /></Field>
      </div>
    </div>
  );
}

function TicketComposer({ kind, schema, refresh, notify, setModal, form, setForm, draft, setDraft, assumptions, setAssumptions }) {
  const [working, setWorking] = useState(false);
  const groups = schema?.resources?.groups?.data || [];
  const companies = schema?.resources?.companies?.data || [];
  const fields = schema?.resources?.ticket_fields?.data || [];
  const customFields = fields.filter((field) => field.name?.startsWith("cf_"));
  const isChange = kind === "change";

  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const setChangeDocument = (changeDocument) => setForm((current) => ({ ...current, change_document: changeDocument }));

  useEffect(() => {
    if (!isChange || !form.change_document) return undefined;
    const timer = window.setTimeout(async () => {
      try {
        const result = await request("/tickets/render-change", {
          method: "POST",
          body: JSON.stringify({ change_document: form.change_document }),
        });
        setForm((current) => current.description === result.rendered_description ? current : { ...current, description: result.rendered_description });
      } catch (error) {
        notify("error", error.message);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [form.change_document, isChange, notify]);

  const useLocalModel = async () => {
    if (!form.rough_notes.trim()) {
      notify("error", "Add rough notes first.");
      return;
    }
    setWorking(true);
    try {
      const result = await request(isChange ? "/local-llm/suggest-change" : "/local-llm/suggest-ticket", {
        method: "POST",
        body: JSON.stringify(isChange ? { text: form.rough_notes } : { kind, text: form.rough_notes }),
      });
      setForm((current) => ({
        ...current,
        ...result.suggestions,
        change_document: result.change_document || current.change_document,
        assumptions: result.assumptions || [],
        skill_version: result.skill_version || "",
        custom_fields: { ...current.custom_fields, ...(result.suggestions.custom_fields || {}) },
      }));
      setAssumptions(result.assumptions || []);
      notify("success", isChange ? "Change draft structured locally. Review the assumptions." : "Draft fields suggested locally. Review before saving.");
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  const saveDraft = async () => {
    setWorking(true);
    try {
      const result = await request(isChange ? "/tickets/draft-change" : "/tickets/draft", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          group_id: form.group_id ? Number(form.group_id) : null,
          company_id: form.company_id ? Number(form.company_id) : null,
        }),
      });
      setDraft(result);
      await refresh();
      notify("success", "Draft saved for review.");
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  const validation = draft?.validation_result;
  return (
    <div className="composer-layout">
      <section className="section composer-main">
        <div className="section-head">
          <div>
            <span className="eyebrow">{isChange ? "Normal Freshdesk ticket with a structured template" : "Standard Freshdesk ticket"}</span>
            <h2>{isChange ? "Draft a change-style ticket" : "Draft a new ticket"}</h2>
          </div>
          <Badge>Review required</Badge>
        </div>
        <Field label={isChange ? "Rough technical notes" : "Rough notes"} span>
          <textarea rows="6" value={form.rough_notes} onChange={(event) => set("rough_notes", event.target.value)} placeholder="Paste or type the facts you want the ticket to contain." />
        </Field>
        <div className="inline-actions">
          <Button type="button" icon={Sparkles} variant="quiet" onClick={useLocalModel} disabled={working}>
            {isChange ? "Structure with local model" : "Draft with local model"}
          </Button>
          <span>{working ? "The local model is generating. Larger models can take a few minutes." : "Notes are checked for likely secrets before they reach the local model."}</span>
        </div>
        {assumptions.length > 0 && (
          <div className="assumption-box">
            <strong>Review inferred values</strong>
            <span>These are editable suggestions based on your notes.</span>
            {assumptions.map((assumption) => <p key={assumption}>{assumption}</p>)}
          </div>
        )}
        <div className="form-grid">
          <Field label="Subject" span>
            <input value={form.subject} onChange={(event) => set("subject", event.target.value)} />
          </Field>
          <Field label="Requester email">
            <input type="email" value={form.requester_email} onChange={(event) => set("requester_email", event.target.value)} />
          </Field>
          <Field label="Requester name">
            <input value={form.requester_name} onChange={(event) => set("requester_name", event.target.value)} />
          </Field>
          <Field label="Group">
            <select value={form.group_id} onChange={(event) => set("group_id", event.target.value)}>
              <option value="">Select a group</option>
              {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
            </select>
          </Field>
          <Field label="Company">
            <select value={form.company_id} onChange={(event) => set("company_id", event.target.value)}>
              <option value="">Select a company</option>
              {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </Field>
          <Field label="Type">
            <input value={form.type} onChange={(event) => set("type", event.target.value)} placeholder="Use the discovered value if required" />
          </Field>
          <Field label="Priority">
            <select value={form.priority} onChange={(event) => set("priority", Number(event.target.value))}>
              <option value={1}>Low</option>
              <option value={2}>Medium</option>
              <option value={3}>High</option>
              <option value={4}>Urgent</option>
            </select>
          </Field>
          <Field label="Status">
            <select value={form.status} onChange={(event) => set("status", Number(event.target.value))}>
              <option value={2}>Open</option>
              <option value={3}>Pending</option>
            </select>
          </Field>
          {!isChange && <Field label="Description" span><textarea rows="14" value={form.description} onChange={(event) => set("description", event.target.value)} placeholder="Write the exact ticket description." /></Field>}
        </div>
        {isChange && form.change_document && <ChangeSectionEditor document={form.change_document} setDocument={setChangeDocument} />}
        {customFields.length > 0 && (
          <div className="custom-fields">
            <h3>Discovered custom fields</h3>
            <div className="form-grid">
              {customFields.map((field) => (
                <Field key={field.name} label={field.label || field.name}>
                  {choiceValues(field.choices).length ? (
                    <select
                      value={form.custom_fields[field.name] || ""}
                      onChange={(event) => set("custom_fields", { ...form.custom_fields, [field.name]: event.target.value })}
                    >
                      <option value="">Select a value</option>
                      {choiceValues(field.choices).map((choice) => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
                    </select>
                  ) : (
                    <input
                      value={form.custom_fields[field.name] || ""}
                      onChange={(event) => set("custom_fields", { ...form.custom_fields, [field.name]: event.target.value })}
                    />
                  )}
                </Field>
              ))}
            </div>
          </div>
        )}
        <div className="submit-row">
          <Button variant="dark" icon={FileClock} onClick={saveDraft} disabled={working}>Save draft for review</Button>
        </div>
      </section>

      <aside className="section review-panel">
        <div className="section-head">
          <div>
            <span className="eyebrow">Exact outgoing payload</span>
            <h2>Approval review</h2>
          </div>
        </div>
        {isChange && form.description && (
          <div className="change-preview">
            <span className="eyebrow">Freshdesk description preview</span>
            <div dangerouslySetInnerHTML={{ __html: form.description }} />
          </div>
        )}
        {!draft ? (
          <Empty title="No saved draft" text="Save a draft to run required-field and sensitive-data validation." />
        ) : (
          <>
            <Badge tone={validation.valid ? "good" : "alert"}>{validation.valid ? "Ready to create" : "Needs attention"}</Badge>
            <dl className="payload-list">
              <div><dt>Subject</dt><dd>{draft.payload.subject}</dd></div>
              <div><dt>Requester</dt><dd>{draft.payload.email}</dd></div>
              <div><dt>Description</dt><dd className={isChange ? "rich-description" : "preserve"}>{isChange ? <span dangerouslySetInnerHTML={{ __html: draft.payload.description }} /> : draft.payload.description}</dd></div>
            </dl>
            {!validation.valid && (
              <div className="validation-box">
                <strong>Cannot create ticket yet</strong>
                {validation.missing_fields.map((field) => <span key={field.name}>{field.label} <small>{field.type}</small></span>)}
                {validation.sensitive_data_findings.map((finding) => <span key={finding.kind}>{finding.message}</span>)}
              </div>
            )}
            <Button
              variant="dark"
              icon={Check}
              disabled={!validation.valid}
              onClick={() => setModal({ kind: "create", draftId: draft.draft_id, subject: draft.payload.subject })}
            >
              Approve and create
            </Button>
          </>
        )}
      </aside>
    </div>
  );
}

function BatchTickets({ refresh, notify, setModal, workspace, setWorkspace }) {
  const { text, baseSubject, baseDescription, batch, selected } = workspace;
  const [editing, setEditing] = useState(null);
  const updateWorkspace = (values) => setWorkspace((current) => ({ ...current, ...values }));
  const setBatch = (updater) => setWorkspace((current) => ({
    ...current,
    batch: typeof updater === "function" ? updater(current.batch) : updater,
  }));
  const setSelected = (updater) => setWorkspace((current) => ({
    ...current,
    selected: typeof updater === "function" ? updater(current.selected) : updater,
  }));

  const draftBatch = async () => {
    try {
      const result = await request("/tickets/draft-batch", {
        method: "POST",
        body: JSON.stringify({ text, base_subject: baseSubject, base_description: baseDescription }),
      });
      setBatch(result);
      setSelected(result.drafts.filter((draft) => draft.validation_result.valid).map((draft) => draft.draft_id));
      await refresh();
      notify("success", `${result.drafts.length} batch drafts created.`);
    } catch (error) {
      notify("error", error.message);
    }
  };

  const toggle = (draftId) =>
    setSelected((current) => current.includes(draftId) ? current.filter((id) => id !== draftId) : [...current, draftId]);

  const saveEdit = async () => {
    try {
      const updated = await request(`/tickets/drafts/${editing.draft_id}`, {
        method: "PUT",
        body: JSON.stringify({
          subject: editing.payload.subject,
          description: editing.payload.description,
          requester_email: editing.payload.email,
        }),
      });
      setBatch((current) => ({ ...current, drafts: current.drafts.map((draft) => draft.draft_id === updated.draft_id ? updated : draft) }));
      setSelected((current) => updated.validation_result.valid ? current : current.filter((id) => id !== updated.draft_id));
      setEditing(null);
      await refresh();
      notify("success", "Batch draft updated.");
    } catch (error) {
      notify("error", error.message);
    }
  };

  const deleteDraft = async (draftId) => {
    try {
      await request(`/tickets/drafts/${draftId}`, { method: "DELETE" });
      setBatch((current) => ({ ...current, drafts: current.drafts.filter((draft) => draft.draft_id !== draftId) }));
      setSelected((current) => current.filter((id) => id !== draftId));
      if (editing?.draft_id === draftId) setEditing(null);
      await refresh();
      notify("success", "Batch draft deleted.");
    } catch (error) {
      notify("error", error.message);
    }
  };

  return (
    <section className="section">
      <div className="section-head">
        <div>
          <span className="eyebrow">One reviewed Freshdesk ticket per row</span>
          <h2>Draft repetitive tickets</h2>
        </div>
        <Badge>{batch ? `${batch.drafts.length} drafts` : "CSV, table, or JSON"}</Badge>
      </div>
      <div className="form-grid">
        <Field label="Base subject"><input value={baseSubject} onChange={(event) => updateWorkspace({ baseSubject: event.target.value })} /></Field>
        <Field label="Base description"><input value={baseDescription} onChange={(event) => updateWorkspace({ baseDescription: event.target.value })} /></Field>
        <Field label="Paste batch data" hint="Include a header row. Example headers: name, email, department, manager, start date, site, required access, device requirement." span>
          <textarea rows="10" value={text} onChange={(event) => updateWorkspace({ text: event.target.value })} placeholder={"name,email,department,manager,start_date,site,required_access,device_requirement"} />
        </Field>
      </div>
      <div className="submit-row">
        <Button variant="dark" icon={Files} onClick={draftBatch} disabled={!text.trim()}>Parse into drafts</Button>
      </div>
      {batch && (
        <div className="batch-review">
          <div className="section-head">
            <h2>Review generated drafts</h2>
            <Button
              variant="dark"
              icon={Check}
              disabled={!selected.length}
              onClick={() => setModal({ kind: "batch", batchId: batch.batch_id, draftIds: selected })}
            >
              Create selected ({selected.length})
            </Button>
          </div>
          {batch.drafts.map((draft) => (
            <div className="batch-row" key={draft.draft_id}>
              <input aria-label={`Select ${draft.payload.subject}`} type="checkbox" checked={selected.includes(draft.draft_id)} disabled={!draft.validation_result.valid} onChange={() => toggle(draft.draft_id)} />
              <div>
                <strong>{draft.payload.subject}</strong>
                <span>{draft.payload.email || "Requester email required"}</span>
              </div>
              <Badge tone={draft.validation_result.valid ? "good" : "alert"}>{draft.validation_result.valid ? "Ready" : "Needs attention"}</Badge>
              <Button variant="quiet" onClick={() => setEditing(draft)}>Edit</Button>
              <Button variant="text" onClick={() => deleteDraft(draft.draft_id)}>Delete</Button>
            </div>
          ))}
        </div>
      )}
      {editing && (
        <div className="batch-editor">
          <div className="section-head">
            <h2>Edit batch draft</h2>
            <Button variant="text" onClick={() => setEditing(null)}>Close</Button>
          </div>
          <div className="form-grid">
            <Field label="Subject" span><input value={editing.payload.subject} onChange={(event) => setEditing({ ...editing, payload: { ...editing.payload, subject: event.target.value } })} /></Field>
            <Field label="Requester email" span><input value={editing.payload.email} onChange={(event) => setEditing({ ...editing, payload: { ...editing.payload, email: event.target.value } })} /></Field>
            <Field label="Description" span><textarea rows="10" value={editing.payload.description} onChange={(event) => setEditing({ ...editing, payload: { ...editing.payload, description: event.target.value } })} /></Field>
          </div>
          <Button variant="dark" onClick={saveEdit}>Save draft changes</Button>
        </div>
      )}
    </section>
  );
}

function SchemaPage({ schema, setSchema, refresh, notify }) {
  const sync = async () => {
    try {
      const result = await request("/freshdesk/sync-schema", { method: "POST" });
      setSchema(result);
      await refresh();
      notify("success", "Freshdesk schema synced.");
    } catch (error) {
      notify("error", error.message);
    }
  };
  const resources = schema?.resources || {};
  return (
    <section className="section">
      <div className="section-head">
        <div>
          <span className="eyebrow">Cached locally from Freshdesk</span>
          <h2>Schema discovery</h2>
        </div>
        <Button variant="dark" icon={RefreshCw} onClick={sync}>Sync Freshdesk schema</Button>
      </div>
      <p className="section-copy">The gateway validates drafts against the fields Freshdesk exposes to your account. It records permission-limited resources instead of guessing.</p>
      <div className="resource-grid">
        {["ticket_fields", "groups", "agents", "companies", "ticket_forms"].map((key) => (
          <article className="resource-card" key={key}>
            <span>{key.replaceAll("_", " ")}</span>
            <strong>{resources[key]?.status === "fallback" ? "Available with fallback" : resources[key]?.status || "Not synced"}</strong>
            <small>{resources[key]?.error || `${resources[key]?.data?.length ?? 0} cached records`}</small>
          </article>
        ))}
      </div>
      <div className="schema-columns">
        <div>
          <h3>Required ticket fields</h3>
          {(schema?.required_fields || []).length ? schema.required_fields.map((field) => (
            <div className="schema-line" key={field.id || field.name}>
              <strong>{field.label || field.name}</strong>
              <span>{field.type}</span>
            </div>
          )) : <Empty title="No required fields cached" text="Sync the schema after configuring Freshdesk." />}
        </div>
        <div>
          <h3>Groups</h3>
          {(resources.groups?.data || []).map((group) => (
            <div className="schema-line" key={group.id}><strong>{group.name}</strong><span>{group.id}</span></div>
          ))}
        </div>
        <div>
          <h3>Agents</h3>
          {(resources.agents?.data || []).map((agent) => (
            <div className="schema-line" key={agent.id}><strong>{agent.contact?.name || agent.name || agent.id}</strong><span>{agent.id}</span></div>
          ))}
        </div>
      </div>
    </section>
  );
}

function RelatedTickets({ notify }) {
  const [tickets, setTickets] = useState([]);
  const [summary, setSummary] = useState("");
  const [working, setWorking] = useState(false);

  const load = async () => {
    setWorking(true);
    try {
      setTickets(await request("/tickets/related-to-me"));
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  const summarise = async (ticket) => {
    try {
      const result = await request("/local-llm/summarise", {
        method: "POST",
        body: JSON.stringify({ text: `${ticket.subject}\n\n${ticket.description}` }),
      });
      setSummary(result.text);
    } catch (error) {
      notify("error", error.message);
    }
  };

  return (
    <section className="section">
      <div className="section-head">
        <div>
          <span className="eyebrow">Constrained identity-based lookup</span>
          <h2>Tickets related to me</h2>
        </div>
        <Button variant="dark" icon={Search} onClick={load} disabled={working}>Search related tickets</Button>
      </div>
      <p className="section-copy">This search uses your configured name and email. It does not expose unrestricted Freshdesk search.</p>
      {summary && <div className="summary-box"><strong>Local model summary</strong><p className="preserve">{summary}</p></div>}
      {tickets.length ? tickets.map((ticket) => (
        <article className="ticket-result" key={ticket.id}>
          <div>
            <span>Ticket #{ticket.id}</span>
            <strong>{ticket.subject}</strong>
            <small>{ticket.related_because.join(", ")}</small>
          </div>
          <Button variant="quiet" icon={Sparkles} onClick={() => summarise(ticket)}>Summarise locally</Button>
        </article>
      )) : <Empty title="No search results loaded" text="Run the identity-based search when you need it." />}
    </section>
  );
}

function AuditPage({ audit, setAudit, notify }) {
  const [mode, setMode] = useState("");
  const load = async (nextMode = mode) => {
    try {
      const query = nextMode ? `?limit=200&action_mode=${nextMode}` : "?limit=200";
      setAudit(await request(`/audit${query}`));
    } catch (error) {
      notify("error", error.message);
    }
  };
  useEffect(() => { load(); }, []);
  return (
    <section className="section">
      <div className="section-head">
        <div>
          <span className="eyebrow">Local SQLite only</span>
          <h2>Audit log</h2>
        </div>
        <select value={mode} onChange={(event) => { setMode(event.target.value); load(event.target.value); }}>
          <option value="">All actions</option>
          <option value="read">Freshdesk reads</option>
          <option value="write">Freshdesk writes</option>
          <option value="local">Local actions</option>
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Action</th><th>Mode</th><th>Draft</th><th>Ticket</th><th>Result</th></tr></thead>
          <tbody>
            {audit.map((event) => (
              <tr key={event.id}>
                <td>{formatDate(event.created_at)}</td>
                <td>{event.action_type.replaceAll("_", " ")}</td>
                <td><Badge>{event.action_mode}</Badge></td>
                <td>{event.draft_id?.slice(0, 8) || "—"}</td>
                <td>{event.ticket_id || "—"}</td>
                <td>{event.error || event.approval_result || event.api_result || "Recorded"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SettingsPage({ notify, refresh }) {
  const [settings, setSettings] = useState(null);
  const [changeSkill, setChangeSkill] = useState(null);
  const [models, setModels] = useState([]);
  const [modelProvider, setModelProvider] = useState("");
  const [directoryQuery, setDirectoryQuery] = useState("");
  const [directoryType, setDirectoryType] = useState("contacts");
  const [directoryResults, setDirectoryResults] = useState([]);

  const loadModels = useCallback(async (showNotice = false) => {
    try {
      const result = await request("/local-llm/models");
      setModels(result.models || []);
      setModelProvider(result.provider || "");
      if (showNotice) notify(result.connected ? "success" : "error", result.connected ? "Local model list refreshed." : result.error);
    } catch (error) {
      if (showNotice) notify("error", error.message);
    }
  }, [notify]);

  useEffect(() => {
    request("/settings").then(setSettings).catch((error) => notify("error", error.message));
    request("/local-llm/change-skill").then(setChangeSkill).catch((error) => notify("error", error.message));
    loadModels();
  }, [loadModels, notify]);

  const save = async () => {
    try {
      const result = await request("/settings", { method: "PUT", body: JSON.stringify(settings) });
      setSettings(result);
      await refresh();
      notify("success", "Local settings updated.");
    } catch (error) {
      notify("error", error.message);
    }
  };
  const test = async (target) => {
    try {
      const result = await request(`/${target}/test`, { method: "POST" });
      if (target === "local-llm" && result.connected) {
        setModels(result.available_models || []);
        setModelProvider(result.provider || "");
      }
      notify(result.connected ? "success" : "error", result.connected ? `${target === "freshdesk" ? "Freshdesk" : "Local model"} connection succeeded.` : result.error);
    } catch (error) {
      notify("error", error.message);
    }
  };
  const searchDirectory = async () => {
    try {
      setDirectoryResults(await request(`/freshdesk/search-${directoryType}`, {
        method: "POST",
        body: JSON.stringify({ query: directoryQuery }),
      }));
    } catch (error) {
      notify("error", error.message);
    }
  };
  if (!settings) return <Empty title="Loading settings" />;
  return (
    <div className="settings-layout">
      <section className="section">
        <div className="section-head"><div><span className="eyebrow">Local configuration</span><h2>Connections and limits</h2></div></div>
        <div className="form-grid">
          <Field label="Freshdesk domain"><input value={settings.freshdesk_domain} disabled /></Field>
          <Field label="Freshdesk API key"><input value="Stored in backend .env only" disabled /></Field>
          <Field label="Local model URL"><input value={settings.local_llm_url} onChange={(event) => setSettings({ ...settings, local_llm_url: event.target.value })} /></Field>
          <Field label="Local model provider">
            <select value={settings.local_llm_provider} onChange={(event) => setSettings({ ...settings, local_llm_provider: event.target.value })}>
              <option value="auto">Auto-detect</option>
              <option value="ollama">Ollama</option>
              <option value="openai-compatible">OpenAI-compatible local server</option>
            </select>
          </Field>
          <Field label="Local model" hint={modelProvider ? `Discovered from ${modelProvider}` : "Refresh after starting your local model server."}>
            {models.length ? (
              <select value={settings.local_llm_model} onChange={(event) => setSettings({ ...settings, local_llm_model: event.target.value })}>
                {!models.includes(settings.local_llm_model) && <option value={settings.local_llm_model}>{settings.local_llm_model}</option>}
                {models.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            ) : (
              <input value={settings.local_llm_model} onChange={(event) => setSettings({ ...settings, local_llm_model: event.target.value })} />
            )}
          </Field>
          <Field label="Local generation timeout (seconds)"><input type="number" min="30" max="1800" value={settings.local_llm_generation_timeout_seconds} onChange={(event) => setSettings({ ...settings, local_llm_generation_timeout_seconds: Number(event.target.value) })} /></Field>
          <Field label="Writes per hour"><input type="number" value={settings.max_writes_per_hour} onChange={(event) => setSettings({ ...settings, max_writes_per_hour: Number(event.target.value) })} /></Field>
          <Field label="Reads per hour"><input type="number" value={settings.max_reads_per_hour} onChange={(event) => setSettings({ ...settings, max_reads_per_hour: Number(event.target.value) })} /></Field>
          <Field label="Ticket creations per hour"><input type="number" value={settings.max_ticket_creations_per_hour} onChange={(event) => setSettings({ ...settings, max_ticket_creations_per_hour: Number(event.target.value) })} /></Field>
          <Field label="Draft expiry minutes"><input type="number" value={settings.draft_expiry_minutes} onChange={(event) => setSettings({ ...settings, draft_expiry_minutes: Number(event.target.value) })} /></Field>
        </div>
        <div className="submit-row">
          <Button variant="dark" onClick={save}>Save settings</Button>
          <Button variant="quiet" onClick={() => test("freshdesk")}>Test Freshdesk</Button>
          <Button variant="quiet" onClick={() => test("local-llm")}>Test local model</Button>
          <Button variant="quiet" icon={RefreshCw} onClick={() => loadModels(true)}>Refresh model list</Button>
        </div>
      </section>
      <section className="section">
        <div className="section-head"><div><span className="eyebrow">Freshdesk directory</span><h2>Search contacts or companies</h2></div></div>
        <div className="search-row">
          <select value={directoryType} onChange={(event) => setDirectoryType(event.target.value)}>
            <option value="contacts">Contacts</option>
            <option value="companies">Companies</option>
          </select>
          <input value={directoryQuery} onChange={(event) => setDirectoryQuery(event.target.value)} placeholder="Search Freshdesk" />
          <Button variant="dark" icon={Search} onClick={searchDirectory} disabled={!directoryQuery.trim()}>Search</Button>
        </div>
        {directoryResults.map((result) => (
          <div className="schema-line" key={result.id}><strong>{result.name || result.email || result.id}</strong><span>{result.email || result.id}</span></div>
        ))}
      </section>
      <section className="section help-panel">
        <div className="section-head"><div><span className="eyebrow">Safety boundaries</span><h2>What this gateway does</h2></div></div>
        <p>Every Freshdesk write needs an exact draft review and explicit typed confirmation. The API key stays in the backend process and local .env file.</p>
        <p>This MVP creates normal Freshdesk tickets only. Change-style tickets are standard tickets with a configurable structured description.</p>
        <p>Cloud AI is disabled. A local model server is optional; manual drafts continue to work without one.</p>
        <p>For setup and terminal STOP-file instructions, open <code>GUIDE.md</code> in the project folder.</p>
      </section>
      {changeSkill && (
        <section className="section help-panel skill-panel">
          <div className="section-head">
            <div><span className="eyebrow">Read-only local instruction file</span><h2>Change drafting skill</h2></div>
            <Badge>Version {changeSkill.version}</Badge>
          </div>
          <p>{changeSkill.summary}</p>
          <div className="skill-sections">
            {changeSkill.sections.map((section) => <span key={section}>{section}</span>)}
          </div>
          <details>
            <summary>View active instructions</summary>
            <pre>{changeSkill.instructions}</pre>
          </details>
        </section>
      )}
    </div>
  );
}

function DraftLine({ draft }) {
  return (
    <div className="list-line">
      <FileClock size={16} />
      <div><strong>{draft.payload.subject || "Untitled draft"}</strong><span>{draft.kind} · {formatDate(draft.created_at)}</span></div>
      <Badge tone={draft.validation_result.valid ? "good" : "alert"}>{draft.validation_result.valid ? "Ready" : "Incomplete"}</Badge>
    </div>
  );
}

function AuditLine({ event }) {
  return (
    <div className="list-line">
      <Activity size={16} />
      <div><strong>{event.action_type.replaceAll("_", " ")}</strong><span>{formatDate(event.created_at)}</span></div>
      <Badge>{event.action_mode}</Badge>
    </div>
  );
}

export default App;
