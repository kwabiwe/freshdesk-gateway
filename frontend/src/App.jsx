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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const agentToken = window.localStorage.getItem("agent_api_token");
  if (path.startsWith("/v1/") && agentToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${agentToken}`;
  }
  const response = await fetch(`${API}${path}`, {
    headers,
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
  ["agent", "AI Agent review", Activity],
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

function displayActionType(value) {
  const legacyProviderKey = ["open", "claw"].join("");
  return String(value || "")
    .replaceAll(legacyProviderKey, "ai_agent")
    .replace(/^agent_/, "ai_agent_")
    .replaceAll("_", " ")
    .replaceAll("ai agent", "AI Agent");
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
  const [agentDraft, setAgentDraft] = useState(null);
  const [agentMetadata, setAgentMetadata] = useState(null);
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
          {activePage === "agent" && (
            <AgentReview
              draft={agentDraft}
              setDraft={setAgentDraft}
              metadata={agentMetadata}
              setMetadata={setAgentMetadata}
              setModal={setModal}
              notify={notify}
            />
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
              setPage={setPage}
              setAgentDraft={setAgentDraft}
              setAgentMetadata={setAgentMetadata}
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
      {modal?.kind === "agent-submit" && (
        <Modal
          title={modal.title}
          copy={modal.copy}
          confirmWord={modal.confirmWord}
          actionLabel={modal.actionLabel}
          onClose={() => setModal(null)}
          onConfirm={modal.onConfirm}
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

function schemaFieldForReviewField(metadata, field) {
  const exactName = field?.schema_field_name || field?.key || "";
  const exact = (metadata?.ticket_fields || []).find((item) => item.name === exactName);
  if (exact) return exact;
  const preferred = {
    form: ["cf_form2"],
    ticket_type: ["cf_type", "cf_ticket_type"],
    business_impact: ["cf_business_impact723800"],
    change_type: ["cf_change_type"],
    requested_by: ["cf_requested_by"],
    change_owner: ["cf_change_owner"],
    change_category: ["cf_change_catergory", "cf_change_category"],
    chg_business_impact: ["cf_chg_business_impact"],
    change_state: ["cf_change_state"],
    approval_state: ["cf_approval_state"],
    customer: ["cf_customer967575"],
    reminder_date: ["cf_reminder_date"],
  }[field?.key] || [];
  for (const name of preferred) {
    const match = (metadata?.ticket_fields || []).find((item) => item.name === name);
    if (match) return match;
  }
  return null;
}

function optionRecords(metadata, field, currentValue) {
  const key = field?.key || "";
  const blank = { value: "", label: "--" };
  const includeCurrent = (items) => {
    const value = currentValue || "";
    if (!value || items.some((item) => item.value === value || item.label === value)) return items;
    return [{ value, label: value }, ...items];
  };
  if (key === "status") return includeCurrent(["Open", "Pending", "Resolved", "Closed"].map((value) => ({ value, label: value })));
  if (key === "priority") return includeCurrent(["Low", "Medium", "High", "Urgent"].map((value) => ({ value, label: value })));
  if (key === "group") return includeCurrent((metadata?.groups || []).map((group) => ({ value: group.name, label: group.name })));
  if (key === "agent") return includeCurrent((metadata?.agents || []).map((agent) => ({ value: agent.contact?.name || agent.name || String(agent.id), label: agent.contact?.name || agent.name || String(agent.id) })));
  if (Array.isArray(field?.choices) && field.choices.length) {
    return includeCurrent([blank, ...field.choices.map((value) => ({ value: String(value), label: String(value) }))]);
  }
  const schemaField = schemaFieldForReviewField(metadata, field);
  const choices = choiceValues(schemaField?.choices).map((value) => ({ value: String(value), label: String(value) }));
  return includeCurrent(choices.length ? [blank, ...choices] : []);
}

function contactCompanyIds(contact) {
  const ids = new Set();
  if (contact?.company_id != null && contact.company_id !== "") ids.add(String(contact.company_id));
  (contact?.other_companies || []).forEach((item) => {
    const id = typeof item === "object" ? item.company_id || item.id : item;
    if (id != null && id !== "") ids.add(String(id));
  });
  return ids;
}

function contactLabel(contact) {
  const name = contact?.name || "";
  const email = contact?.email || "";
  if (name && email) return `${name} <${email}>`;
  return name || email || String(contact?.id || "");
}

function contactMatches(contact, query) {
  const wanted = query.trim().toLowerCase();
  if (wanted.length < 2) return true;
  return [contactLabel(contact), contact?.email, contact?.name, contact?.company_name]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(wanted));
}

function companyLabel(company) {
  return company?.name || company?.company_name || String(company?.id || "");
}

function agentLabel(agent) {
  return agent?.contact?.name || agent?.name || agent?.contact?.email || String(agent?.id || "");
}

function productRecords(metadata, field) {
  const products = Array.isArray(metadata?.products) ? metadata.products : [];
  if (products.length) return products;
  const schemaField = schemaFieldForReviewField(metadata, field);
  if (schemaField?.choices && typeof schemaField.choices === "object" && !Array.isArray(schemaField.choices)) {
    return Object.entries(schemaField.choices)
      .filter(([, id]) => !Array.isArray(id) && typeof id !== "object")
      .map(([name, id]) => ({ id, name }));
  }
  return [];
}

function selectableEntityRecords(metadata, field) {
  if (field.key === "company") return (metadata?.companies || []).map((company) => ({ id: company.id, label: companyLabel(company), record: company }));
  if (field.key === "product") return productRecords(metadata, field).map((product) => ({ id: product.id, label: product.name || String(product.id), record: product }));
  if (field.key === "group") return (metadata?.groups || []).map((group) => ({ id: group.id, label: group.name || String(group.id), record: group }));
  if (field.key === "agent") return (metadata?.agents || []).map((agent) => ({ id: agent.id, label: agentLabel(agent), record: agent }));
  return [];
}

function relationshipFieldPatch(field, selected) {
  return {
    ...field,
    value: selected.label,
    display_value: selected.label,
    resolved_id: selected.id,
    record: selected.record || {},
    source: "user_edit",
    status: "confirmed",
    field_errors: [],
    warnings: [],
    missing_reason: "",
  };
}

function isDirectoryField(field) {
  return ["company", "product", "group", "agent"].includes(field?.key);
}

function fieldValue(field) {
  return field?.display_value || field?.value || "";
}

function displayToken(value, fallback = "unknown") {
  return String(value || fallback).replaceAll("_", " ");
}

function draftSubject(draft) {
  return fieldValue(draft?.envelope?.ticket_fields?.find((field) => field.key === "subject")) || draft?.draft_id || "Untitled AI Agent draft";
}

function sortAgentDrafts(drafts) {
  return [...drafts].sort((a, b) => {
    const createdDelta = Date.parse(b.created_at || 0) - Date.parse(a.created_at || 0);
    if (createdDelta) return createdDelta;
    return Date.parse(b.updated_at || 0) - Date.parse(a.updated_at || 0);
  });
}

function AgentEntityFieldEditor({ field, ticketFields, metadata, commitFields, notify, disabled }) {
  const value = fieldValue(field);
  const companyField = ticketFields.find((item) => item.key === "company");
  const selectedCompanyId = companyField?.resolved_id ? String(companyField.resolved_id) : "";
  const selectedCompanyName = companyField?.display_value || companyField?.value || "";
  const [query, setQuery] = useState(value);
  const [searchResults, setSearchResults] = useState([]);
  const [companyContacts, setCompanyContacts] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setQuery(value);
  }, [field.key, field.resolved_id, value]);

  useEffect(() => {
    if (field.key !== "contact" || !selectedCompanyId) {
      setCompanyContacts([]);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    request(`/freshdesk/contacts?company_id=${encodeURIComponent(selectedCompanyId)}`)
      .then((items) => {
        if (!cancelled) setCompanyContacts(Array.isArray(items) ? items : []);
      })
      .catch((error) => {
        if (!cancelled) notify("error", error.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [field.key, notify, selectedCompanyId]);

  useEffect(() => {
    if (field.key !== "contact") return undefined;
    const trimmed = query.trim();
    if (trimmed.length < 2 || trimmed === value) {
      setSearchResults([]);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      request("/freshdesk/search-contacts", {
        method: "POST",
        body: JSON.stringify({ query: trimmed }),
      })
        .then((items) => {
          if (!cancelled) setSearchResults(Array.isArray(items) ? items : []);
        })
        .catch((error) => {
          if (!cancelled) notify("error", error.message);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [field.key, notify, query, value]);

  const clearContactPatch = () => ({
    ...field,
    value: "",
    display_value: "",
    resolved_id: null,
    email: "",
    company_id: null,
    other_company_ids: [],
    record: {},
    source: "user_edit",
    status: field.required ? "missing" : "needs_human_choice",
    field_errors: [],
    warnings: [],
    missing_reason: "",
  });

  const selectContact = (contact) => {
    const ids = contactCompanyIds(contact);
    if (selectedCompanyId && !ids.has(selectedCompanyId)) {
      notify("error", "That Freshdesk contact is not linked to the selected company.");
      return;
    }
    const companyId = selectedCompanyId || String(contact.company_id || Array.from(ids)[0] || "");
    const company = (metadata?.companies || []).find((item) => String(item.id) === companyId);
    const patches = [
      {
        ...field,
        value: contactLabel(contact),
        display_value: contactLabel(contact),
        resolved_id: contact.id,
        email: contact.email || "",
        company_id: contact.company_id || null,
        other_company_ids: Array.from(ids),
        record: contact,
        source: "user_edit",
        status: "confirmed",
        field_errors: [],
        warnings: [],
        missing_reason: "",
      },
    ];
    if (companyField && companyId) {
      patches.push(
        relationshipFieldPatch(companyField, {
          id: companyId,
          label: companyLabel(company || { id: companyId, name: contact.company_name }),
          record: company || { id: companyId, name: contact.company_name },
        })
      );
    }
    commitFields(patches);
  };

  if (field.key === "contact") {
    const companyPool = companyContacts.filter((contact) => contactMatches(contact, query));
    const searchPool = selectedCompanyId
      ? searchResults.filter((contact) => contactCompanyIds(contact).has(selectedCompanyId))
      : searchResults;
    const contacts = [...companyPool, ...searchPool].filter(
      (contact, index, items) => contact?.id && items.findIndex((item) => String(item.id) === String(contact.id)) === index
    );
    return (
      <div className="entity-picker">
        {selectedCompanyId ? (
          <div className="entity-context">
            <Building2 size={14} />
            <span>Showing contacts linked to {selectedCompanyName || selectedCompanyId}</span>
          </div>
        ) : null}
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={selectedCompanyId ? "Search contacts in selected company" : "Search existing Freshdesk contacts"}
          aria-label="Search existing Freshdesk contacts"
          disabled={disabled}
        />
        <div className="entity-results">
          {loading ? <span className="entity-empty">Searching Freshdesk...</span> : null}
          {contacts.map((contact) => (
            <button
              type="button"
              className={cls("entity-result", String(field.resolved_id || "") === String(contact.id) && "entity-result-selected")}
              key={contact.id}
              onClick={() => selectContact(contact)}
              disabled={disabled}
            >
              <strong>{contactLabel(contact)}</strong>
              <span>{contact.company_name || companyLabel((metadata?.companies || []).find((company) => String(company.id) === String(contact.company_id))) || "No company on contact"}</span>
            </button>
          ))}
          {!loading && query.trim().length >= 2 && !contacts.length ? (
            <span className="entity-empty">No matching Freshdesk contacts. Choose an existing contact from Freshdesk metadata.</span>
          ) : null}
          {!loading && query.trim().length < 2 && !selectedCompanyId ? (
            <span className="entity-empty">Type at least 2 characters to search Freshdesk contacts.</span>
          ) : null}
          {!loading && selectedCompanyId && !contacts.length ? (
            <span className="entity-empty">No contacts returned for the selected company.</span>
          ) : null}
        </div>
        {field.resolved_id ? (
          <Button type="button" variant="text" onClick={() => commitFields([clearContactPatch()])} disabled={disabled}>
            Clear selected contact
          </Button>
        ) : null}
      </div>
    );
  }

  if (isDirectoryField(field)) {
    const records = selectableEntityRecords(metadata, field);
    return (
      <div className="entity-picker">
        <select
          value={field.resolved_id ? String(field.resolved_id) : ""}
          onChange={(event) => {
            const selected = records.find((record) => String(record.id) === event.target.value);
            if (!selected) {
              commitFields([
                {
                  ...field,
                  value: "",
                  display_value: "",
                  resolved_id: null,
                  record: {},
                  source: "user_edit",
                  status: field.required ? "missing" : "needs_human_choice",
                  field_errors: [],
                  warnings: [],
                  missing_reason: "",
                },
              ]);
              return;
            }
            const patches = [relationshipFieldPatch(field, selected)];
            if (field.key === "company") {
              const contactField = ticketFields.find((item) => item.key === "contact");
              if (contactField?.resolved_id) {
                const contactIds = contactCompanyIds({ company_id: contactField.company_id, other_companies: contactField.record?.other_companies || contactField.other_company_ids || [] });
                if (!contactIds.has(String(selected.id))) patches.push({
                  ...contactField,
                  value: "",
                  display_value: "",
                  resolved_id: null,
                  email: "",
                  company_id: null,
                  other_company_ids: [],
                  record: {},
                  source: "user_edit",
                  status: contactField.required ? "missing" : "needs_human_choice",
                  field_errors: [],
                  warnings: [],
                  missing_reason: "Select a contact linked to the selected company.",
                });
              }
            }
            commitFields(patches);
          }}
          disabled={disabled}
        >
          <option value="">Select {field.label || field.key}</option>
          {records.map((record) => <option key={`${field.key}-${record.id}`} value={record.id}>{record.label}</option>)}
        </select>
        {!records.length ? <span className="entity-empty">No synced Freshdesk records available for this field.</span> : null}
      </div>
    );
  }

  return null;
}

function guidanceForSection(key) {
  return {
    scope: "Define what changes and what stays out of scope.",
    implementation: "List the exact steps in the order they will be carried out.",
    rollback: "State the rollback trigger and the exact reversal steps.",
    verification: "Name the checks that prove the change worked.",
    config_items: "Include device, mailbox, service, application, or other configuration item names.",
    requester_context: "Explain the requester/customer context the AI agent used.",
    assumptions_missing: "Keep assumptions and missing details visible for review.",
  }[key] || "Review this section before approval.";
}

function AgentReview({ draft, setDraft, metadata, setMetadata, setModal, notify }) {
  const [tab, setTab] = useState("review");
  const [working, setWorking] = useState(false);
  const [agentToken, setAgentToken] = useState(() => window.localStorage.getItem("agent_api_token") || "");
  const [authError, setAuthError] = useState("");
  const [agentDrafts, setAgentDrafts] = useState([]);
  const validation = draft?.validation_result || draft?.envelope?.validation || { valid: false, blocking: [] };
  const envelope = draft?.envelope;
  const ticketFields = Array.isArray(envelope?.ticket_fields) ? envelope.ticket_fields : [];
  const descriptionSections = Array.isArray(envelope?.description_sections) ? envelope.description_sections : [];
  const sources = Array.isArray(envelope?.sources) ? envelope.sources : [];
  const inferredItems = Array.isArray(envelope?.assumptions) ? envelope.assumptions : [];
  const missingItems = Array.isArray(envelope?.missing_information) ? envelope.missing_information : [];
  const payloadPreview = draft?.payload_preview || null;
  const rawEvents = draft?.revision_events || envelope?.revision?.events || [];
  const events = Array.isArray(rawEvents) ? rawEvents : [];
  const changedKeys = new Set(events.map((event) => event.field_key));
  const fieldCount = ticketFields.length;
  const readyCount = ticketFields.filter((field) => !["missing", "needs_human_choice", "conflict"].includes(field.status)).length;

  const saveAgentToken = useCallback(() => {
    if (agentToken.trim()) window.localStorage.setItem("agent_api_token", agentToken.trim());
    else window.localStorage.removeItem("agent_api_token");
    setAuthError("");
    setMetadata(null);
    setDraft(null);
    notify("success", agentToken.trim() ? "Agent API token saved in this browser." : "Agent API token removed from this browser.");
  }, [agentToken, notify, setDraft, setMetadata]);

  const loadReviewWorkspace = useCallback(async ({ preferSaved = true } = {}) => {
    setWorking(true);
    try {
      const meta = await request("/v1/metadata");
      setMetadata(meta);
      setAuthError("");
      const items = await request("/v1/drafts?limit=50");
      const sortedItems = sortAgentDrafts(Array.isArray(items) ? items : []);
      setAgentDrafts(sortedItems);
      const savedId = preferSaved ? window.localStorage.getItem("ai_agent_review_draft_id") : "";
      const newest = sortedItems[0] || null;
      if (savedId) {
        const saved = sortedItems.find((item) => item.draft_id === savedId);
        const savedCreated = Date.parse(saved?.created_at || 0);
        const newerAwaiting = sortedItems.some((item) =>
          item.approval_status === "awaiting_approval" && Date.parse(item.created_at || 0) > savedCreated
        );
        if (saved && !newerAwaiting) {
          setDraft(saved);
          return;
        }
        window.localStorage.removeItem("ai_agent_review_draft_id");
      }
      if (newest) {
        window.localStorage.setItem("ai_agent_review_draft_id", newest.draft_id);
        setDraft(newest);
      } else {
        window.localStorage.removeItem("ai_agent_review_draft_id");
        setDraft(null);
      }
    } catch (error) {
      if (error.message.includes("Agent API token") || error.message.includes("401")) {
        setAuthError(error.message);
        setMetadata(null);
      } else {
        notify("error", error.message);
      }
    } finally {
      setWorking(false);
    }
  }, [notify, setDraft, setMetadata]);

  useEffect(() => {
    if (!draft && !metadata) loadReviewWorkspace();
  }, [draft, loadReviewWorkspace, metadata]);

  const selectAgentDraft = async (draftId) => {
    if (!draftId) return;
    setWorking(true);
    try {
      const selected = await request(`/v1/drafts/${draftId}`);
      window.localStorage.setItem("ai_agent_review_draft_id", selected.draft_id);
      setDraft(selected);
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  const removeAgentDraft = async () => {
    if (!draft?.draft_id) return;
    if (!window.confirm(`Remove ${draft.draft_id} from the local gateway inbox? This does not touch Freshdesk.`)) return;
    setWorking(true);
    try {
      await request(`/v1/drafts/${draft.draft_id}`, { method: "DELETE" });
      window.localStorage.removeItem("ai_agent_review_draft_id");
      notify("success", "AI Agent draft removed from the local inbox.");
      await loadReviewWorkspace({ preferSaved: false });
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  const localUpdateField = (key, value) => {
    setDraft((current) => {
      const currentFields = Array.isArray(current.envelope.ticket_fields) ? current.envelope.ticket_fields : [];
      const nextFields = currentFields.map((field) =>
        field.key === key ? { ...field, value, display_value: value, source: "user_edit" } : field
      );
      return { ...current, envelope: { ...current.envelope, ticket_fields: nextFields } };
    });
  };

  const commitField = async (field) => {
    try {
      const result = await request(`/v1/drafts/${draft.draft_id}`, {
        method: "PATCH",
        body: JSON.stringify({ edited_by: "kb", ticket_fields: [field] }),
      });
      setDraft(result);
    } catch (error) {
      notify("error", error.message);
    }
  };

  const commitFields = async (fields) => {
    try {
      const result = await request(`/v1/drafts/${draft.draft_id}`, {
        method: "PATCH",
        body: JSON.stringify({ edited_by: "kb", ticket_fields: fields }),
      });
      setDraft(result);
    } catch (error) {
      notify("error", error.message);
    }
  };

  const localUpdateSection = (key, content) => {
    setDraft((current) => {
      const currentSections = Array.isArray(current.envelope.description_sections) ? current.envelope.description_sections : [];
      const nextSections = currentSections.map((section) =>
        section.key === key ? { ...section, content, status: content.trim() ? "confirmed" : "missing" } : section
      );
      return { ...current, envelope: { ...current.envelope, description_sections: nextSections } };
    });
  };

  const commitSection = async (section) => {
    try {
      const result = await request(`/v1/drafts/${draft.draft_id}`, {
        method: "PATCH",
        body: JSON.stringify({ edited_by: "kb", description_sections: [section] }),
      });
      setDraft(result);
    } catch (error) {
      notify("error", error.message);
    }
  };

  const approvalPhrase = (mode) => ({ update: "UPDATE", bulk_create: "CREATE BULK" }[mode] || "CREATE");

  const submitApprovedDraft = async (word) => {
    setWorking(true);
    try {
      const result = await request(`/v1/drafts/${draft.draft_id}/approve-and-submit`, {
        method: "POST",
        body: JSON.stringify({ confirmation: word }),
      });
      setDraft(result);
      setModal(null);
      const verb = envelope.mode === "update" ? "updated" : envelope.mode === "bulk_create" ? "tickets created" : "ticket created";
      notify("success", `Freshdesk ${verb}. Feedback event is ready for the AI agent.`);
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  const approve = async () => {
    const mode = envelope.mode || "create";
    const confirmWord = approvalPhrase(mode);
    setModal({
      kind: "agent-submit",
      title: mode === "update" ? "Update this Freshdesk ticket?" : mode === "bulk_create" ? "Create these Freshdesk tickets?" : "Create this Freshdesk ticket?",
      copy: mode === "bulk_create"
        ? `Review complete. This submits ${envelope.bulk_items?.length || 0} generated tickets to Freshdesk.`
        : `Review complete. This sends the exact approved AI Agent draft to Freshdesk: ${fieldValue(ticketFields.find((field) => field.key === "subject")) || "Untitled ticket"}`,
      confirmWord,
      actionLabel: mode === "update" ? "Update ticket" : mode === "bulk_create" ? "Create tickets" : "Create ticket",
      onConfirm: submitApprovedDraft,
    });
  };

  const saveReview = async () => {
    setWorking(true);
    try {
      const result = await request(`/v1/drafts/${draft.draft_id}`, {
        method: "PATCH",
        body: JSON.stringify({
          edited_by: "kb",
          reason: "Saved from review screen",
          ticket_fields: envelope.ticket_fields,
          description_sections: envelope.description_sections,
        }),
      });
      setDraft(result);
      notify("success", "Review changes saved.");
    } catch (error) {
      notify("error", error.message);
    } finally {
      setWorking(false);
    }
  };

  if (!metadata) {
    return (
      <section className="section">
        <div className="section-head">
          <div>
            <span className="eyebrow">AI Agent draft handoff</span>
            <h2>{authError ? "Agent API token required" : "Loading review workspace"}</h2>
          </div>
        </div>
        {authError ? (
          <>
            <p className="section-copy">The gateway inbox is protected. Paste the same `AGENT_API_TOKEN` from the MacBook gateway `.env`; it is saved only in this browser's local storage.</p>
            <div className="settings-grid">
              <Field label="Agent API token">
                <input type="password" value={agentToken} onChange={(event) => setAgentToken(event.target.value)} />
              </Field>
              <div className="field">
                <span className="field-label">Load gateway inbox</span>
                <Button
                  type="button"
                  variant="dark"
                  icon={ShieldCheck}
                  onClick={() => {
                    saveAgentToken();
                    window.setTimeout(() => loadReviewWorkspace({ preferSaved: true }), 0);
                  }}
                  disabled={working}
                >
                  Save token and retry
                </Button>
              </div>
            </div>
            <Empty title={authError} text="Without this browser token, the AI Agent review inbox cannot read submitted OpenClaw drafts." />
          </>
        ) : <Empty title="Loading gateway metadata" text="The review page is connecting to the local Freshdesk gateway." />}
      </section>
    );
  }

  if (!draft || !envelope) {
    return (
      <div className="agent-page">
        <section className="agent-hero">
          <div>
            <span className="eyebrow">A24 AI Agent to Freshdesk</span>
            <h2>Gateway inbox is empty</h2>
            <p>This is the gateway inbox for OpenClaw-submitted drafts. OpenClaw writes drafts to <code>POST /api/v1/drafts</code>; the gateway stores them in the local MacBook SQLite `agent_drafts` table and shows them here for approval.</p>
          </div>
          <div className="agent-hero-actions">
            <Badge>Waiting for draft</Badge>
            <Button type="button" icon={RefreshCw} variant="quiet" onClick={() => loadReviewWorkspace({ preferSaved: false })} disabled={working}>Refresh drafts</Button>
          </div>
        </section>
        <section className="section">
          <div className="section-head">
            <div>
              <span className="eyebrow">Next handoff</span>
              <h2>How OpenClaw connects</h2>
            </div>
            <Badge>{metadata?.schema_version}</Badge>
          </div>
          <p className="section-copy">OpenClaw posts a versioned draft envelope to <code>POST /api/v1/drafts</code>. After that, refresh this page and review the exact fields that will be mapped into the Freshdesk API payload on approval.</p>
        </section>
        <AgentApiPanel metadata={metadata} />
      </div>
    );
  }

  return (
    <div className="agent-page">
      <section className="agent-hero">
        <div>
          <span className="eyebrow">A24 AI Agent to Freshdesk</span>
          <h2>Gateway inbox: review this OpenClaw draft before anything is submitted</h2>
          <p>OpenClaw submitted this draft envelope into the MacBook gateway. The gateway owns validation, diffs, approval, and the final Freshdesk handoff.</p>
        </div>
        <div className="agent-hero-actions">
          {agentDrafts.length > 1 && (
            <label className="agent-draft-select">
              <span>Current inbox draft</span>
              <select value={draft.draft_id} onChange={(event) => selectAgentDraft(event.target.value)} disabled={working}>
                {agentDrafts.map((item) => (
                  <option value={item.draft_id} key={item.draft_id}>
                    {draftSubject(item)} - {formatDate(item.created_at)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Badge>{draft.draft_id}</Badge>
          <Badge tone={validation.valid ? "good" : "alert"}>{validation.valid ? "Ready for approval" : "Needs review"}</Badge>
          <Button type="button" icon={RefreshCw} variant="quiet" onClick={() => loadReviewWorkspace({ preferSaved: false })} disabled={working}>Refresh drafts</Button>
          {draft.approval_status !== "submitted" && (
            <Button type="button" icon={X} variant="danger" onClick={removeAgentDraft} disabled={working}>Remove from inbox</Button>
          )}
        </div>
      </section>

      <div className="agent-tabs">
        <button type="button" className={cls(tab === "review" && "agent-tab-active")} onClick={() => setTab("review")}>Field ledger</button>
        <button type="button" className={cls(tab === "bulk" && "agent-tab-active")} onClick={() => setTab("bulk")}>Bulk pattern</button>
        <button type="button" className={cls(tab === "api" && "agent-tab-active")} onClick={() => setTab("api")}>AI Agent API</button>
      </div>

      {tab === "review" && (
        <div className="agent-layout">
          <section className="agent-ledger">
            <div className="agent-ledger-head">
              <div>
                <span className="eyebrow">Numbered Freshdesk field ledger</span>
                <h2>{readyCount} of {fieldCount} fields ready</h2>
              </div>
              <div className="ledger-head-actions">
                <Badge>{changedKeys.size} changed</Badge>
                <Button type="button" variant="quiet" icon={FileClock} onClick={saveReview} disabled={working}>Save review changes</Button>
              </div>
            </div>
            {ticketFields.map((field, index) => {
              const value = fieldValue(field);
              const options = optionRecords(metadata, field, value);
              const original = events.find((event) => event.field_key === field.key)?.old_value || value;
              return (
                <article className={cls("ledger-row", changedKeys.has(field.key) && "ledger-row-changed")} key={field.key}>
                  <div className="ledger-number">{String(index + 1).padStart(2, "0")}</div>
                  <div className="ledger-field-main">
                    <div className="ledger-field-title">
                      <strong>{field.label}</strong>
                      <Badge tone={["missing", "needs_human_choice", "conflict"].includes(field.status) ? "alert" : "neutral"}>{displayToken(field.status, "unknown")}</Badge>
                    </div>
                    <div className="ledger-edit">
                      {field.kind === "entity_ref" || isDirectoryField(field) || field.key === "contact" ? (
                        <AgentEntityFieldEditor
                          field={field}
                          ticketFields={ticketFields}
                          metadata={metadata}
                          commitFields={commitFields}
                          notify={notify}
                          disabled={working}
                        />
                      ) : options.length > 1 ? (
                        <select
                          value={value}
                          onChange={(event) => {
                            const next = { ...field, value: event.target.value, display_value: event.target.value, source: "user_edit" };
                            localUpdateField(field.key, event.target.value);
                            commitField(next);
                          }}
                        >
                          {options.map((option) => <option key={`${field.key}-${option.value}`} value={option.value}>{option.label}</option>)}
                        </select>
                      ) : (
                        <input
                          value={value}
                          onChange={(event) => localUpdateField(field.key, event.target.value)}
                          onBlur={(event) => commitField({ ...field, value: event.target.value, display_value: event.target.value, source: "user_edit" })}
                        />
                      )}
                    </div>
                    <p>{field.why_this_value || field.missing_reason || "Review this value before approval."}</p>
                    {Array.isArray(field.field_errors) && field.field_errors.length ? (
                      <ReviewList items={field.field_errors} empty="" />
                    ) : null}
                  </div>
                  <dl className="ledger-meta">
                    <div><dt>Original</dt><dd>{original || "Empty"}</dd></div>
                    <div><dt>Source</dt><dd>{field.source}</dd></div>
                    <div><dt>Confidence</dt><dd>{field.confidence == null ? "Not set" : `${Math.round(field.confidence * 100)}%`}</dd></div>
                    <div><dt>Payload path</dt><dd>{field.payload_path || "Not sent"}</dd></div>
                    <div><dt>Freshdesk ID</dt><dd>{field.resolved_id || "Not resolved"}</dd></div>
                  </dl>
                </article>
              );
            })}

            <div className="description-ledger">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Freshdesk Description</span>
                  <h2>Sections combined into one Description field</h2>
                </div>
              </div>
              <p className="section-copy">These sections are combined and sent to the single Freshdesk Description field.</p>
              {descriptionSections.map((section, index) => (
                <article className={cls("section-editor", !String(section.content || "").trim() && "section-editor-missing")} key={section.key}>
                  <div className="ledger-number">{String(index + 1).padStart(2, "0")}</div>
                  <div>
                    <div className="ledger-field-title">
                      <strong>{section.title}</strong>
                      <Badge tone={!String(section.content || "").trim() ? "alert" : "neutral"}>{displayToken(section.status, "unknown")}</Badge>
                    </div>
                    <small>{guidanceForSection(section.key)}</small>
                    <textarea
                      rows={section.key === "implementation" ? 7 : 5}
                      value={section.content || ""}
                      onChange={(event) => localUpdateSection(section.key, event.target.value)}
                      onBlur={(event) => commitSection({ ...section, content: event.target.value })}
                    />
                  </div>
                </article>
              ))}
            </div>
          </section>

          <aside className="agent-review-panel">
            <section className="section">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Evidence</span>
                  <h2>Why the AI Agent chose this</h2>
                </div>
              </div>
              {sources.map((source) => (
                <article className="source-line" key={source.id}>
                  <span>{source.kind}</span>
                  <strong>{source.title}</strong>
                  <p>{source.snippet}</p>
                </article>
              ))}
            </section>

            <section className="section">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Inferred and missing</span>
                  <h2>What the drafter assumed</h2>
                </div>
              </div>
              <div className="validation-box">
                <strong>Inferred values</strong>
                <ReviewList items={inferredItems.map((item) => item.text || String(item))} empty="No inferred values recorded." />
              </div>
              <div className="validation-box">
                <strong>Missing information</strong>
                <ReviewList
                  items={missingItems}
                  empty="No missing information recorded."
                  render={(item) => `${item.field || "Field"}: ${item.reason || item}`}
                />
              </div>
            </section>

            <section className="section">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Final Freshdesk payload</span>
                  <h2>Exact payload before approval</h2>
                </div>
                <Badge tone={payloadPreview?.validation?.valid ? "good" : "alert"}>
                  {payloadPreview?.validation?.valid ? "Valid" : "Blocked"}
                </Badge>
              </div>
              <p className="section-copy">Description is one payload field. UI-only review names such as Product, Contact, Company, Group, Agent, and Form must be resolved or mapped before submission. Company is sent only when it can be verified for the selected Contact.</p>
              <pre className="feedback-json payload-preview-json">{JSON.stringify(payloadPreview?.payload || {}, null, 2)}</pre>
              {payloadPreview?.mapping_notes?.length ? (
                <div className="validation-box">
                  <strong>Mapping notes</strong>
                  <ReviewList items={payloadPreview.mapping_notes} empty="No mapping notes." />
                </div>
              ) : null}
            </section>

            <section className="section">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Validation</span>
                  <h2>{validation.valid ? "No blockers" : "Approval blocked"}</h2>
                </div>
              </div>
              <ReviewList items={validation.blocking || []} empty="No blocking validation issues." />
              <div className="validation-box">
                <strong>Warnings</strong>
                <ReviewList items={validation.warnings || []} empty="No warnings." />
              </div>
              <Button variant="dark" icon={Check} disabled={!validation.valid || working || draft.approval_status === "submitted"} onClick={approve}>
                {draft.approval_status === "submitted"
                  ? "Submitted"
                  : envelope.mode === "update"
                    ? "Update Freshdesk ticket"
                    : envelope.mode === "bulk_create"
                      ? "Create Freshdesk tickets"
                      : "Create Freshdesk ticket"}
              </Button>
            </section>

            <section className="section">
              <div className="section-head">
                <div>
                  <span className="eyebrow">Immutable revisions</span>
                  <h2>What changed</h2>
                </div>
              </div>
              {events.length ? events.slice().reverse().map((event, index) => (
                <article className="revision-line" key={`${event.field_key}-${event.timestamp}-${index}`}>
                  <strong>{displayToken(event.field_key, "unknown field")}</strong>
                  <span>Changed from {event.old_value || "Empty"} to {event.new_value || "Empty"}</span>
                  <small>{event.edited_by} at {formatDate(event.timestamp)}</small>
                </article>
              )) : <Empty title="No user edits yet" text="Edits will be recorded here and sent back to the AI agent after approval." />}
            </section>

            {draft.feedback_payload && (
              <section className="section">
                <div className="section-head">
                  <div>
                    <span className="eyebrow">AI Agent feedback event</span>
                    <h2>{draft.ticket_id}</h2>
                  </div>
                </div>
                <pre className="feedback-json">{JSON.stringify(draft.feedback_payload, null, 2)}</pre>
              </section>
            )}
          </aside>
        </div>
      )}

      {tab === "bulk" && <AgentBulkPreview envelope={envelope} />}
      {tab === "api" && <AgentApiPanel metadata={metadata} />}
    </div>
  );
}

function AgentBulkPreview({ envelope }) {
  const rows = envelope?.bulk_items || [];
  const isBulk = envelope?.mode === "bulk_create";
  return (
    <section className="section agent-bulk">
      <div className="section-head">
        <div>
          <span className="eyebrow">bulk_create mode</span>
          <h2>One template, many reviewable tickets</h2>
        </div>
        <Badge>{isBulk ? `${rows.length} rows` : "Not a bulk draft"}</Badge>
      </div>
      <p className="section-copy">When OpenClaw submits a bulk-create envelope, each row is validated and shown here before the gateway creates anything in Freshdesk.</p>
      <div className="bulk-template-grid">
        <article>
          <span>Template</span>
          <strong>{fieldValue(envelope?.ticket_fields?.find((field) => field.key === "subject")) || "No template subject"}</strong>
          <p>Shared defaults and review edits are merged with each submitted row at approval time.</p>
        </article>
        <article>
          <span>Rows</span>
          <strong>{rows.length} tickets</strong>
          <p>Each row inherits the template and records its own missing information.</p>
        </article>
      </div>
      {rows.length ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Row</th><th>Ticket focus</th><th>Gateway state</th></tr></thead>
            <tbody>
              {rows.map((row) => {
                const subject = fieldValue(row.ticket_fields?.find((field) => field.key === "subject")) || row.title || row.row_id;
                const valid = row.validation?.valid;
                return (
                  <tr key={row.row_id}>
                    <td>{row.row_id}</td>
                    <td>{subject}</td>
                    <td>{valid ? "Ready" : "Needs review"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <Empty title="No bulk rows on this draft" text="Submit a bulk_create envelope from OpenClaw to review row-level tickets here." />}
    </section>
  );
}

function AgentApiPanel({ metadata }) {
  const [token, setToken] = useState(() => window.localStorage.getItem("agent_api_token") || "");
  const endpoints = [
    "GET /api/v1/metadata",
    "GET /api/v1/drafts?limit=20",
    "POST /api/v1/drafts",
    "GET /api/v1/drafts/{id}",
    "PATCH /api/v1/drafts/{id}",
    "POST /api/v1/drafts/{id}/validate",
    "GET /api/v1/drafts/{id}/payload-preview",
    "POST /api/v1/drafts/{id}/approve-and-submit {confirmation}",
    "POST /api/v1/feedback/approved-drafts",
  ];
  return (
    <section className="section">
      <div className="section-head">
        <div>
          <span className="eyebrow">Machine-friendly local handoff</span>
          <h2>AI agents submit drafts, the gateway submits tickets</h2>
        </div>
        <Badge>{metadata?.schema_version}</Badge>
      </div>
      <p className="section-copy">The gateway accepts structured drafts, validates against cached Freshdesk metadata, and returns an explicit feedback event after approval.</p>
      <div className="api-route-grid">
        {endpoints.map((endpoint) => <code key={endpoint}>{endpoint}</code>)}
      </div>
      <div className="settings-grid">
        <Field label="Agent API token">
          <input type="password" value={token} onChange={(event) => setToken(event.target.value)} />
        </Field>
        <div className="field">
          <span className="field-label">Browser token store</span>
          <Button
            type="button"
            variant="quiet"
            icon={ShieldCheck}
            onClick={() => {
              if (token) window.localStorage.setItem("agent_api_token", token);
              else window.localStorage.removeItem("agent_api_token");
            }}
          >
            Save token
          </Button>
        </div>
      </div>
      <div className="validation-box">
        <strong>Freshdesk form binding</strong>
        <span>{metadata?.freshdesk_form_binding?.message}</span>
      </div>
    </section>
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
  change_review: null,
  skill_version: "",
};

function textLines(value) {
  return (value || "").split("\n").map((line) => line.trim()).filter(Boolean);
}

function configurationItemLines(items) {
  return (items || []).map((item) => [item.name, item.item_type, item.site_location, item.purpose, item.version].join(" | ")).join("\n");
}

function rollbackLines(branches) {
  return (branches || []).flatMap((branch) => (branch.steps || []).map((step) => `${branch.scenario || "Rollback"} | ${step}`)).join("\n");
}

function parseConfigurationItems(value) {
  return textLines(value).map((line) => {
    const [name = "TBD", item_type = "", site_location = "", purpose = "", version = ""] = line.split("|").map((item) => item.trim());
    return { name, item_type, site_location, purpose, version };
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

function riskMitigationLines(items) {
  return (items || []).map((item) => `${item.risk || "TBD"} | ${item.mitigation || "TBD"}`).join("\n");
}

function parseRiskMitigations(value) {
  return textLines(value).map((line) => {
    const [risk = "TBD", ...mitigationParts] = line.split("|").map((item) => item.trim());
    return { risk, mitigation: mitigationParts.join(" | ") || "TBD" };
  });
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
        <Field label="Change type"><input value={document.change_type || ""} onChange={(event) => set("change_type", event.target.value)} /></Field>
        <Field label="Workflow state"><input value={document.workflow_state || ""} onChange={(event) => set("workflow_state", event.target.value)} /></Field>
        <Field label="Planned change date"><input value={document.planned_change_date || ""} onChange={(event) => set("planned_change_date", event.target.value)} /></Field>
        <Field label="Planned start"><input value={document.planned_start || ""} onChange={(event) => set("planned_start", event.target.value)} /></Field>
        <Field label="Planned end"><input value={document.planned_end || ""} onChange={(event) => set("planned_end", event.target.value)} /></Field>
        <Field label="Customer"><input value={document.customer || ""} onChange={(event) => set("customer", event.target.value)} /></Field>
        <Field label="Environment" span><input value={document.environment || ""} onChange={(event) => set("environment", event.target.value)} /></Field>
        <Field label="Background of change" span><textarea rows="5" value={document.background || ""} onChange={(event) => set("background", event.target.value)} /></Field>
        <Field label="Change description" span><textarea rows="5" value={document.change_description || ""} onChange={(event) => set("change_description", event.target.value)} /></Field>
        <Field label="Configuration items" hint="One per line: name | type | site or environment | role in change | version" span>
          <textarea rows="5" value={configurationItemLines(document.configuration_items)} onChange={(event) => set("configuration_items", parseConfigurationItems(event.target.value))} />
        </Field>
        <Field label="Implementation steps" hint="One ordered step per line" span><textarea rows="8" value={(document.implementation_steps || []).join("\n")} onChange={(event) => set("implementation_steps", textLines(event.target.value))} /></Field>
        <Field label="Rollback branches" hint="One step per line: scenario | rollback action" span><textarea rows="6" value={rollbackLines(document.rollback_branches)} onChange={(event) => set("rollback_branches", parseRollbackBranches(event.target.value))} /></Field>
        <Field label="Pre-change verification"><textarea rows="5" value={verification.pre_change.join("\n")} onChange={(event) => setVerification("pre_change", event.target.value)} /></Field>
        <Field label="In-change verification"><textarea rows="5" value={verification.in_change.join("\n")} onChange={(event) => setVerification("in_change", event.target.value)} /></Field>
        <Field label="Post-change verification" span><textarea rows="5" value={verification.post_change.join("\n")} onChange={(event) => setVerification("post_change", event.target.value)} /></Field>
        <Field label="Risk"><textarea rows="3" value={document.risk || ""} onChange={(event) => set("risk", event.target.value)} /></Field>
        <Field label="Impact"><textarea rows="3" value={document.impact || ""} onChange={(event) => set("impact", event.target.value)} /></Field>
        <Field label="Risk and impact summary" span><textarea rows="4" value={document.risk_and_impact || ""} onChange={(event) => set("risk_and_impact", event.target.value)} /></Field>
        <Field label="Risks and mitigations" hint="One per line: risk | mitigation" span>
          <textarea rows="5" value={riskMitigationLines(document.risks_and_mitigations)} onChange={(event) => set("risks_and_mitigations", parseRiskMitigations(event.target.value))} />
        </Field>
        <Field label="Communication plan" hint="One communication action per line" span><textarea rows="4" value={(document.communication_plan || []).join("\n")} onChange={(event) => set("communication_plan", textLines(event.target.value))} /></Field>
        <Field label="Expected outcome" span><textarea rows="4" value={document.expected_outcome || ""} onChange={(event) => set("expected_outcome", event.target.value)} /></Field>
        <Field label="Success criteria" hint="One criterion per line" span><textarea rows="5" value={(document.success_criteria || []).join("\n")} onChange={(event) => set("success_criteria", textLines(event.target.value))} /></Field>
        <Field label="Dependencies" hint="One dependency per line" span><textarea rows="4" value={(document.dependencies || []).join("\n")} onChange={(event) => set("dependencies", textLines(event.target.value))} /></Field>
        <Field label="Open questions for review" hint="These remain local review notes and are not rendered into the Freshdesk Description." span>
          <textarea rows="4" value={(document.open_questions || []).join("\n")} onChange={(event) => set("open_questions", textLines(event.target.value))} />
        </Field>
      </div>
    </div>
  );
}

function ReviewList({ items, empty = "None", render = (item) => item }) {
  if (!items?.length) return <span className="review-empty">{empty}</span>;
  return <ul>{items.map((item, index) => <li key={`${JSON.stringify(item)}-${index}`}>{render(item)}</li>)}</ul>;
}

function ChangeGenerationReview({ review, fields }) {
  if (!review) return null;
  const labels = Object.fromEntries((fields || []).map((field) => [field.name, field.label || field.name]));
  const mapped = Object.entries(review.freshdesk_fields?.custom_fields || {});
  const summaryFields = Object.entries(review.freshdesk_fields || {})
    .filter(([name, value]) => !["description", "custom_fields"].includes(name) && value != null && value !== "");
  const validation = review.validation_preview || {};
  return (
    <div className="generation-review">
      <div className="section-head">
        <div><span className="eyebrow">Pre-save validation preview</span><h3>Review generated Freshdesk mapping</h3></div>
        <Badge tone={validation.valid ? "good" : "alert"}>{validation.valid ? "Ready to save" : "Needs details"}</Badge>
      </div>
      <div className="review-grid">
        <article className="review-card">
          <strong>Auto-filled Freshdesk fields</strong>
          <ReviewList
            items={[...summaryFields, ...mapped]}
            empty="No Freshdesk fields were auto-filled."
            render={([name, value]) => <><b>{labels[name] || name}</b><span>{String(value)}</span></>}
          />
        </article>
        <article className={cls("review-card", review.missing_required_fields?.length && "review-card-alert")}>
          <strong>Missing required fields</strong>
          <ReviewList
            items={review.missing_required_fields}
            empty="No missing required Freshdesk fields."
            render={(field) => <><b>{field.label || field.name}</b><span>{field.type || "required field"}</span></>}
          />
        </article>
        <article className={cls("review-card", review.open_questions?.length && "review-card-alert")}>
          <strong>Open questions</strong>
          <ReviewList items={review.open_questions} empty="No open questions." />
        </article>
        <article className={cls("review-card", review.tbd_fields?.length && "review-card-alert")}>
          <strong>TBD values</strong>
          <ReviewList items={review.tbd_fields} empty="No TBD values." />
        </article>
        <article className="review-card">
          <strong>Field mapping notes</strong>
          <ReviewList items={review.field_mapping_notes} empty="No mapping notes." />
        </article>
        <article className="review-card">
          <strong>Low-confidence fields</strong>
          <ReviewList items={review.low_confidence_fields} empty="No low-confidence mappings." render={(name) => labels[name] || name} />
        </article>
      </div>
    </div>
  );
}

function TicketComposer({ kind, schema, refresh, notify, setModal, setPage, setAgentDraft, setAgentMetadata, form, setForm, draft, setDraft, assumptions, setAssumptions }) {
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
      if (isChange) {
        const result = await request("/tickets/draft-change-review", {
          method: "POST",
          body: JSON.stringify({ text: form.rough_notes }),
        });
        setAgentDraft?.(result.draft);
        setAgentMetadata?.(result.metadata);
        if (result.draft?.draft_id) window.localStorage.setItem("ai_agent_review_draft_id", result.draft.draft_id);
        setAssumptions(result.draft?.envelope?.assumptions?.map((item) => item.text) || []);
        setPage?.("agent");
        notify("success", "Local LLM created a Change Request review draft. Resolve the required Freshdesk fields before approval.");
        return;
      }
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
        change_review: isChange ? {
          freshdesk_fields: result.suggestions || {},
          missing_required_fields: result.missing_required_fields || [],
          open_questions: result.open_questions || [],
          tbd_fields: result.tbd_fields || [],
          field_mapping_notes: result.field_mapping_notes || [],
          low_confidence_fields: result.low_confidence_fields || [],
          validation_preview: result.validation_preview || {},
        } : current.change_review,
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
  const validationMessages = validation ? [
    ...(validation.invalid_fields || []).map((field) => `Unsupported Freshdesk field: ${field}.`),
    ...(validation.invalid_custom_fields || []).map((field) => `Unsupported Freshdesk custom field: ${field}.`),
    ...(validation.invalid_custom_field_values || []).map((field) => `${field.label || field.name} must be one of: ${(field.allowed_values || []).join(", ")}.`),
    ...(validation.invalid_company_association || []).map((item) => item.message || "Requester and company selection do not match Freshdesk company metadata."),
    ...(validation.invalid_tags || []).map(() => "Freshdesk tags must be an array of non-empty strings."),
    ...(validation.warnings || []),
  ] : [];
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
        {isChange && <ChangeGenerationReview review={form.change_review} fields={fields} />}
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
            <div className="validation-box">
              <strong>Outgoing Freshdesk payload</strong>
              <pre className="feedback-json payload-preview-json">{JSON.stringify(draft.payload || {}, null, 2)}</pre>
            </div>
            {!validation.valid && (
              <div className="validation-box">
                <strong>Cannot create ticket yet</strong>
                {validation.missing_fields.map((field) => <span key={field.name}>{field.label} <small>{field.type}</small></span>)}
                {validation.sensitive_data_findings.map((finding) => <span key={finding.kind}>{finding.message}</span>)}
                <ReviewList items={validationMessages} empty="" />
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
                <td>{displayActionType(event.action_type)}</td>
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
  const [skillRegistry, setSkillRegistry] = useState(null);
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
    request("/local-llm/skills").then(setSkillRegistry).catch((error) => notify("error", error.message));
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
          <p>Active local skill: <code>{changeSkill.id}</code>. Add future skills as manifest-backed folders under <code>skills/</code>.</p>
          <div className="skill-sections">
            {changeSkill.sections.map((section) => <span key={section}>{section}</span>)}
          </div>
          <details>
            <summary>View active instructions</summary>
            <pre>{changeSkill.instructions}</pre>
          </details>
          {skillRegistry?.skills?.length > 0 && (
            <>
              <h3>Discovered local skills</h3>
              {skillRegistry.skills.map((skill) => (
                <div className="schema-line" key={skill.id}>
                  <strong>{skill.name}</strong>
                  <span>{skill.id} · v{skill.version}</span>
                </div>
              ))}
            </>
          )}
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
      <div><strong>{displayActionType(event.action_type)}</strong><span>{formatDate(event.created_at)}</span></div>
      <Badge>{event.action_mode}</Badge>
    </div>
  );
}

export default App;
