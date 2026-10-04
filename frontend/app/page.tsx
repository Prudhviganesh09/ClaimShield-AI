"use client";

import {useCallback, useEffect, useRef, useState, type FormEvent} from "react";
import {Activity, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight, Clock3, Download,
  FileCheck2, FileText, FolderOpen, LayoutDashboard, LoaderCircle, LogOut, Plus, Search, Send,
  Settings2, ShieldCheck, Sparkles, Upload, X, AlertTriangle} from "lucide-react";
import {api, ApiError} from "../lib/api";
import type {Analysis, Claim, Detail, Finding, ProviderHealth, Source, Usage, User} from "../lib/types";

const date = (value: string) => new Date(value).toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"});
const label = (value: string) => value.replaceAll("_", " ").toLowerCase();
const money = (value: number | null) => value === null ? "—" : new Intl.NumberFormat(undefined,
  {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(value);

function Badge({value}: {value: string}) {
  return <span className={`badge ${value === "ready" || value === "reviewed" ? "green" : value === "needs_retry" ? "amber" : ""}`}>
    <span className="dot"/>{label(value)}</span>;
}

function Login({onLogin}: {onLogin: (user: User) => void}) {
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    const body = {email: data.get("email"), password: data.get("password"), ...(register ? {name: data.get("name")} : {})};
    try {onLogin(await api<User>(`/auth/${register ? "register" : "login"}`, {method: "POST", body: JSON.stringify(body)}));}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <main className="login-layout">
    <div className="login-story"><div className="brand"><ShieldCheck size={30}/> ClaimShield<span>AI</span></div>
      <div className="story-body"><span className="eyebrow light">CLARITY FOR EVERY CLAIM</span>
        <h1>Strong evidence.<br/>Informed decisions.</h1><p>Turn scattered documents into a clear path forward. Review claim denials, understand policy evidence, and prepare an appeal with confidence.</p>
        <div className="story-points"><span><CheckCircle2/> Evidence-linked conclusions</span><span><CheckCircle2/> Human review at every step</span><span><CheckCircle2/> NVIDIA hosted intelligence</span></div>
      </div><div className="story-footer"><ShieldCheck size={16}/> Built for administrative claim review</div>
    </div>
    <div className="login-form"><div className="form-wrap"><span className="eyebrow">YOUR CLAIM WORKSPACE</span>
      <h2>{register ? "Create your account" : "Welcome back"}</h2><p className="muted">{register ? "Start organizing the evidence behind your claims." : "Sign in to pick up where you left off."}</p>
      <form onSubmit={submit}>{register && <label>Full name<input name="name" required maxLength={120} autoComplete="name"/></label>}
        <label>Email address<input name="email" type="email" required autoComplete="email" placeholder="you@example.com"/></label>
        <label>Password<input name="password" type="password" required minLength={12} maxLength={128} autoComplete={register ? "new-password" : "current-password"}/></label>
        {register && <small className="muted">Use at least 12 characters.</small>}
        {error && <div className="notice error" role="alert">{error}</div>}
        <button className="button primary full" disabled={busy}>{busy ? <LoaderCircle className="spin"/> : <ArrowRight/>}{register ? "Create account" : "Sign in"}</button>
      </form><p className="switch-auth">{register ? "Already have an account?" : "New to ClaimShield?"} <button className="text-button" onClick={() => {setRegister(!register); setError("");}}>{register ? "Sign in" : "Create an account"}</button></p>
      <div className="login-note"><ShieldCheck size={18}/><p>AI assists your review. Every analysis and appeal remains subject to human verification.</p></div>
    </div></div>
  </main>;
}

function NewClaim({onClose, onCreated}: {onClose: () => void; onCreated: (claim: Claim) => void}) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {dialogRef.current?.showModal();}, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    try {onCreated(await api<Claim>("/claims", {method: "POST", body: JSON.stringify({title: form.get("title"),
      claim_number: form.get("claim_number"), insurer: form.get("insurer"), amount: form.get("amount") ? Number(form.get("amount")) : null})}));}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <dialog ref={dialogRef} className="modal" onCancel={onClose} aria-labelledby="new-claim-title">
    <div className="panel-title"><h2 id="new-claim-title">Start a new claim</h2><button className="icon-button" aria-label="Close" onClick={onClose}><X/></button></div>
    <p className="muted">Add the details you have. You can upload supporting evidence next.</p>
    <form onSubmit={submit}><label>Claim title<input autoFocus required name="title" maxLength={200} placeholder="e.g. Authorization denial review"/></label>
      <div className="form-row"><label>Claim number<input name="claim_number" maxLength={100} placeholder="Optional"/></label><label>Amount (document currency)<input name="amount" type="number" min="0" max="1000000000" step="0.01" placeholder="Optional"/></label></div>
      <label>Insurer<input name="insurer" maxLength={200} placeholder="Insurance provider"/></label>
      {error && <div className="notice error" role="alert">{error}</div>}
      <button className="button primary full" disabled={busy}>{busy ? <LoaderCircle className="spin"/> : <Plus/>}Create claim</button>
    </form>
  </dialog>;
}

function Findings({items, sources}: {items: Finding[]; sources: Source[]}) {
  return <div className="findings">{items.map((finding, index) => <article className="finding" key={index}>
    <div className="finding-heading"><span className="finding-number">{String(index+1).padStart(2, "0")}</span><span className={`kind ${finding.kind}`}>{finding.kind}</span></div>
    <p>{finding.statement}</p>{finding.citations.map((citation, i) => {
      const source = sources.find(s => s.chunk_id === citation.chunk_id);
      return <details className="citation" key={i}><summary><FileText size={13}/>{source?.document_name || "Evidence"} · page {source?.page}<ChevronRight size={13}/></summary>
        <blockquote>{citation.quote}</blockquote>{source && <a href={`/api/documents/${source.document_id}/download`} className="text-button"><Download size={13}/>Download source</a>}
      </details>;
    })}
  </article>)}</div>;
}

function AnalysisPanel({analysis, revision}: {analysis: Analysis; revision: number}) {
  const value = analysis.result;
  return <div className="analysis-result">
    <div className="report-intro"><div><span className="eyebrow">{analysis.kind === "appeal" ? "APPEAL DRAFT" : analysis.kind === "chat" ? "EVIDENCE ANSWER" : "CLAIM ASSESSMENT"}</span>
      <h3>{analysis.kind === "appeal" ? "A starting point for your appeal" : "What the evidence tells us"}</h3></div>
      <div className="score"><strong>{value.assessment.evidence_confidence}<small>/100</small></strong><span>Evidence quality</span></div></div>
    {revision !== value.evidence_revision && <div className="notice warning"><Clock3 size={18}/>This report predates changes to the evidence. Run a new analysis to include them.</div>}
    {value.insufficient_evidence && <div className="notice warning"><AlertTriangle size={18}/>The evidence is insufficient for a complete assessment.</div>}
    <p className="muted small">{value.assessment.confidence_explanation}</p>
    <h4>Supported findings</h4><Findings items={value.findings} sources={value.sources}/>
    {!!value.recommendations.length && <><h4>Recommended next steps</h4><Findings items={value.recommendations} sources={value.sources}/></>}
    {!!value.appeal_paragraphs.length && <><h4>Appeal draft · human review required</h4><Findings items={value.appeal_paragraphs} sources={value.sources}/>
      <a className="button secondary" href={`/api/analyses/${analysis.id}/appeal/download`}
        download="claimshield-appeal-draft.txt"><Download size={16}/>Download appeal draft</a></>}
    {(value.missing_information.length > 0 || value.assessment.missing_documents.length > 0) && <div className="missing"><h4>Information to collect</h4>
      <ul>{[...new Set([...value.assessment.missing_documents, ...value.missing_information])].map(item => <li key={item}>{item}</li>)}</ul></div>}
    {!!value.assessment.risk_flags.length && <div className="risk-list">{value.assessment.risk_flags.map(r => <span key={r}><AlertTriangle size={14}/>{r}</span>)}</div>}
    <footer className="report-footer"><ShieldCheck size={16}/><span>Human review required · {date(analysis.created_at)}<br/><small>{analysis.model}{analysis.fallback_used ? " · Configured fallback used" : ""}</small></span></footer>
  </div>;
}

function ClaimWorkspace({id, onBack, onChange}: {id: string; onBack: () => void; onChange: () => void}) {
  const [detail, setDetail] = useState<Detail | null>(null); const [error, setError] = useState("");
  const [busy, setBusy] = useState(""); const [tab, setTab] = useState("analysis");
  const [active, setActive] = useState<Analysis | null>(null); const [question, setQuestion] = useState("");
  const [notes, setNotes] = useState(""); const [reviewStatus, setReviewStatus] = useState("in_review");
  const notesDirty = useRef(false); const reviewStatusDirty = useRef(false);
  const [saved, setSaved] = useState(false); const uploadRef = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async (initial = false) => {
    try {const next = await api<Detail>(`/claims/${id}`); setDetail(next);
      if (initial) {notesDirty.current = false; reviewStatusDirty.current = false;}
      if (!notesDirty.current) setNotes(next.review_notes);
      if (!reviewStatusDirty.current) setReviewStatus(next.status);}
    catch (e) {setError((e as Error).message);}
  }, [id]);
  useEffect(() => {void refresh(true);}, [refresh]);
  const pending = detail?.documents.some(d => d.status === "uploaded" || d.status === "processing");
  useEffect(() => {if (!pending) return; const timer = setInterval(() => {void refresh();}, 2500); return () => clearInterval(timer);}, [pending, refresh]);
  async function run(kind: string) {
    setBusy(kind); setError("");
    try {const body = kind === "chat" ? JSON.stringify({question}) : undefined;
      const report = await api<Analysis>(`/claims/${id}/${kind === "analysis" ? "analyze" : kind}`, {method: "POST", body});
      setActive(report); setTab(kind); if (kind === "chat") setQuestion(""); await refresh(); onChange();
    } catch(e) {setError((e as Error).message);} finally {setBusy("");}
  }
  async function upload(files: FileList | null) {
    if (!files?.length) return; setBusy("upload"); setError("");
    try {for (const file of Array.from(files)) {const form = new FormData(); form.append("file", file);
      await api(`/claims/${id}/documents`, {method: "POST", body: form});}
      await refresh(); onChange();
    } catch(e) {setError((e as Error).message); await refresh();} finally {setBusy(""); if (uploadRef.current) uploadRef.current.value = "";}
  }
  async function retry(documentId: string) {
    setBusy(documentId); setError("");
    try {await api(`/documents/${documentId}/retry`, {method: "POST"});
      setDetail(current => current ? {...current, documents: current.documents.map(d => d.id === documentId ? {...d, status: "processing"} : d)} : current);
      await refresh();}
    catch(e) {setError((e as Error).message);} finally {setBusy("");}
  }
  async function saveReview(event: FormEvent) {
    event.preventDefault(); setBusy("review"); setSaved(false); setError("");
    try {await api(`/claims/${id}/review`, {method: "POST", body: JSON.stringify({status: reviewStatus, notes})});
      notesDirty.current = false; reviewStatusDirty.current = false; setSaved(true); await refresh(); onChange();}
    catch(e) {setError((e as Error).message);} finally {setBusy("");}
  }
  if (!detail) return <div className="empty"><LoaderCircle className="spin"/><p>{error || "Loading claim…"}</p><button className="text-button" onClick={onBack}>Back to claims</button></div>;
  const report = active?.kind === tab ? active : detail.analyses.find(a => a.kind === tab);
  return <>
    <button className="back text-button" onClick={onBack}><ArrowLeft size={16}/>All claims</button>
    <div className="page-heading"><div><span className="eyebrow">CLAIM {detail.claim_number || detail.id.slice(0, 8)}</span><h1>{detail.title}</h1><p className="muted">{detail.insurer || "Insurer not supplied"} · Amount {money(detail.amount)}</p></div><Badge value={detail.status}/></div>
    {error && <div className="notice error" role="alert"><AlertTriangle size={18}/>{error}<button aria-label="Dismiss error" className="icon-button" onClick={() => setError("")}><X size={16}/></button></div>}
    <div className="workspace-grid"><aside className="evidence-panel panel"><div className="panel-title"><h3>Claim evidence</h3><span className="count">{detail.documents.length}</span></div>
      <p className="muted small">Upload denial letters, policies, bills, and claim forms.</p>
      <input ref={uploadRef} className="visually-hidden" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={e => void upload(e.target.files)} aria-label="Upload claim documents"/>
      <button className="upload-zone" disabled={!!busy} onClick={() => uploadRef.current?.click()}><Upload/>
        <strong>{busy === "upload" ? "Saving documents…" : "Add documents"}</strong><small>PDF, PNG, JPEG, or TXT</small></button>
      {pending && <div className="processing"><LoaderCircle className="spin" size={15}/>Extracting and indexing evidence…</div>}
      <div className="document-list">{detail.documents.map(doc => <article className="document-card" key={doc.id}>
        <div className="document-name"><FileText size={20}/><strong>{doc.name}</strong></div><div className="document-meta"><Badge value={doc.status}/><small>{label(doc.document_type)}</small></div>
        {doc.extraction_method && <small className="muted">{doc.extraction_method} · {Math.round(doc.confidence*100)}% extraction confidence</small>}
        {doc.error && <p className="document-error">{doc.error}</p>}
        {!!doc.warnings.length && <details className="doc-warnings"><summary>Extraction warnings ({doc.warnings.length})</summary>{doc.warnings.map(w => <p key={w}>{w}</p>)}</details>}
        {!!Object.keys(doc.fields).length && <details className="doc-warnings"><summary>Extracted fields</summary>{Object.entries(doc.fields).map(([k,v]) => <p key={k}><strong>{label(k)}:</strong> {v}</p>)}</details>}
        <div className="document-actions"><a href={`/api/documents/${doc.id}/download`} className="text-button"><Download size={13}/>Original</a>
          {!['uploaded', 'processing'].includes(doc.status) && <button className="text-button" disabled={!!busy} onClick={() => void retry(doc.id)}>{busy === doc.id ? "Starting…" : doc.status === "ready" ? "Reindex" : "Retry"}</button>}</div>
      </article>)}</div>
      {!detail.documents.length && <p className="muted small centered">Your original files and previous analyses stay available if AI processing is unavailable.</p>}
    </aside><section className="review-panel panel"><div className="tabs" role="tablist" aria-label="Claim review sections">
      {[['analysis','Analysis'], ['chat','Ask evidence'], ['appeal','Appeal draft'], ['review','Human review']].map(([key,title]) => <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => {setTab(key); setSaved(false);}}>{title}</button>)}</div>
      <div className="tab-content" role="tabpanel">
        {tab === "review" ? <form onSubmit={saveReview}><span className="eyebrow">YOUR JUDGMENT, RECORDED</span><h3>Complete the human review</h3><p className="muted">Review the originals and verify each conclusion before using an analysis or appeal.</p>
          <label>Review status<select value={reviewStatus} onChange={e => {reviewStatusDirty.current = true; setSaved(false); setReviewStatus(e.target.value);}}>{['collecting_evidence','ready_for_review','in_review','reviewed'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></label>
          <label>Review notes<textarea rows={8} maxLength={10000} value={notes} onChange={e => {notesDirty.current = true; setNotes(e.target.value); setSaved(false);}} placeholder="Record missing evidence, corrections, and the next administrative step."/></label>
          <button className="button primary" disabled={!!busy}><Check size={16}/>{busy === "review" ? "Saving…" : "Save review"}</button>{saved && <span className="saved" role="status">Review saved</span>}
        </form> : <>
          <div className="action-row"><div className="muted small">{tab === "analysis" ? "Retrieve → reason → verify" : tab === "appeal" ? "Evidence-supported draft for your review" : "Answers grounded in this claim’s documents"}</div>
            {tab !== "chat" && <button className="button primary" disabled={!!busy || !detail.documents.some(d => d.status === "ready")} onClick={() => void run(tab)}>
              {busy === tab ? <LoaderCircle className="spin" size={16}/> : <Sparkles size={16}/>} {busy === tab ? "Reviewing evidence…" : tab === "appeal" ? "Draft appeal" : "Analyze claim"}</button>}</div>
          {tab === "chat" && <form className="question-form" onSubmit={e => {e.preventDefault(); void run("chat");}}><label className="visually-hidden" htmlFor="question">Ask about this claim</label><input id="question" minLength={3} maxLength={1500} required value={question} onChange={e => setQuestion(e.target.value)} placeholder="What evidence supports this denial?"/><button className="button primary" disabled={!!busy || !detail.documents.some(d => d.status === "ready")} aria-label="Ask evidence">{busy === "chat" ? <LoaderCircle className="spin"/> : <Send size={17}/>}</button></form>}
          {busy && ['analysis','appeal','chat'].includes(busy) && <div className="notice"><LoaderCircle className="spin" size={18}/>Retrieving relevant passages and checking the conclusions. This can take a few minutes.</div>}
          {report ? <>{tab === "chat" && <p className="asked-question">{report.question}</p>}<AnalysisPanel analysis={report} revision={detail.revision}/></> : <div className="empty report-empty"><div className="empty-icon"><ShieldCheck size={36}/></div><h3>{tab === "appeal" ? "Build your appeal on evidence" : "Let’s bring clarity to this claim"}</h3><p>Add and index your supporting documents, then {tab === "chat" ? "ask a question about the evidence" : tab === "appeal" ? "prepare an appeal draft" : "run your first analysis"}.</p><div className="steps"><span>01 · Collect</span><ChevronRight size={14}/><span>02 · Analyze</span><ChevronRight size={14}/><span>03 · Review</span></div></div>}
          {!!detail.analyses.filter(a => a.kind === tab).length && <details className="history"><summary>Previous {tab === "chat" ? "answers" : "reports"} ({detail.analyses.filter(a => a.kind === tab).length})</summary>{detail.analyses.filter(a => a.kind === tab).map(a => <button key={a.id} onClick={() => setActive(a)}><Clock3 size={14}/>{date(a.created_at)} · {a.question.slice(0, 60)}<ChevronRight size={14}/></button>)}</details>}
        </>}
      </div>
    </section></div>
  </>;
}

function Admin() {
  const [usage, setUsage] = useState<Usage | null>(null); const [health, setHealth] = useState<ProviderHealth | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => {api<Usage>("/admin/usage").then(setUsage).catch(e => setError(e.message));}, []);
  async function check() {setBusy(true); setError(""); try {setHealth(await api<ProviderHealth>("/admin/providers/nvidia/health")); setUsage(await api<Usage>("/admin/usage"));} catch(e) {setError((e as Error).message);} finally {setBusy(false);}}
  return <><div className="page-heading"><div><span className="eyebrow">PROVIDER OPERATIONS</span><h1>NVIDIA usage</h1><p className="muted">Request activity, model distribution, and provider reachability.</p></div><button className="button secondary" disabled={busy} onClick={() => void check()}>{busy ? <LoaderCircle className="spin" size={16}/> : <Activity size={16}/>}Check provider</button></div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {usage ? <><div className="stats admin-stats">{[["NVIDIA requests",usage.requests],["Requests today",usage.requests_today],["Requests this month",usage.requests_this_month],["Token estimate",usage.token_estimate],["Rate-limit events",usage.rate_limit_events],["Failed requests",usage.failed_requests]].map(([name,value]) => <div className="stat panel" key={name}><span>{name}</span><strong>{Number(value).toLocaleString()}</strong></div>)}</div>
      <div className="admin-grid"><section className="panel"><div className="panel-title"><h3>Model distribution</h3><span className="badge">{usage.mode} mode</span></div>{usage.model_distribution.length ? usage.model_distribution.map(m => <div className="distribution" key={m.model}><div><span>{m.model}</span><strong>{m.requests}</strong></div><div className="bar"><span style={{width: `${m.requests/Math.max(1, usage.requests)*100}%`}}/></div></div>) : <p className="muted">No inference requests recorded yet.</p>}<p className="muted small">Average latency: {(usage.average_latency_ms/1000).toFixed(2)}s. Reporting periods use UTC.</p><p className="muted small">{usage.cost_note}</p></section>
      <section className="panel"><h3>Provider health</h3>{health ? <><div className="health-line"><span>API key configured</span><Badge value={health.configured ? "ready" : "needs_retry"}/></div><div className="health-line"><span>Endpoint reachable</span><Badge value={health.reachable ? "ready" : "needs_retry"}/></div><dl className="health-models"><dt>Reasoning</dt><dd>{health.reasoning_model}</dd><dt>Fast</dt><dd>{health.fast_model}</dd><dt>Embedding</dt><dd>{health.embedding_model}</dd></dl><p className="muted small">{health.note}</p><p className="muted small">Checked {new Date(health.last_checked).toLocaleString()}</p></> : <div className="empty"><Activity/><p>Run a provider check to verify endpoint reachability.</p></div>}</section></div>
    </> : <div className="empty">{!error && <LoaderCircle className="spin"/>}<p>{error ? "Usage could not be loaded." : "Loading usage…"}</p></div>}
  </>;
}

export default function Home() {
  const [user, setUser] = useState<User | null>(null); const [loading, setLoading] = useState(true);
  const [claims, setClaims] = useState<Claim[]>([]); const [view, setView] = useState("dashboard");
  const [selected, setSelected] = useState<string | null>(null); const [newClaim, setNewClaim] = useState(false);
  const [search, setSearch] = useState(""); const [error, setError] = useState(""); const [demoBusy, setDemoBusy] = useState(false);
  const [demoEnabled, setDemoEnabled] = useState(false); const [filter, setFilter] = useState("all");
  const refresh = useCallback(async () => {try {setClaims(await api<Claim[]>("/claims"));} catch(e) {setError((e as Error).message);}}, []);
  useEffect(() => {api<User>("/auth/me").then(setUser).catch(e => {if (!(e instanceof ApiError && e.status === 401)) setError(e.message);}).finally(() => setLoading(false));}, []);
  useEffect(() => {if (user) {void refresh(); api<{demo_mode: boolean}>("/config").then(c => setDemoEnabled(c.demo_mode)).catch(() => {});}}, [user, refresh]);
  async function demo() {setDemoBusy(true); setError(""); try {const claim = await api<Claim>("/demo", {method: "POST"}); await refresh(); setSelected(claim.id);} catch(e) {setError((e as Error).message);} finally {setDemoBusy(false);}}
  async function logout() {try {await api("/auth/logout", {method: "POST"}); setUser(null); setClaims([]); setSelected(null); setError(""); setView("dashboard");} catch(e) {setError((e as Error).message);}}
  if (loading) return <main className="boot"><ShieldCheck size={42}/><LoaderCircle className="spin"/><p>Opening your workspace…</p></main>;
  if (!user) return <>{error && <div className="offline-banner" role="alert">{error}</div>}<Login onLogin={setUser}/></>;
  const filtered = claims.filter(c => `${c.title} ${c.claim_number} ${c.insurer}`.toLowerCase().includes(search.toLowerCase()) && (filter === "all" || c.status === filter));
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><ShieldCheck size={29}/><span>ClaimShield<small>AI</small></span></div><span className="nav-label">WORKSPACE</span>
    <nav>{[["dashboard", "Overview", LayoutDashboard], ["claims", "All claims", FolderOpen], ...(user.role === "admin" ? [["admin", "Provider & usage", Settings2]] : [])].map(([key, title, Icon]) => {
      const NavIcon = Icon as typeof LayoutDashboard; return <button key={String(key)} className={view === key ? "active" : ""} onClick={() => {setView(String(key)); setSelected(null);}}><NavIcon size={18}/>{String(title)}{key === "claims" && <span>{claims.length}</span>}</button>;
    })}</nav><div className="sidebar-tip"><ShieldCheck size={22}/><strong>Evidence comes first.</strong><p>AI supports your judgment. You stay in control of every claim.</p></div><div className="sidebar-footer"><span className="provider-dot"/>NVIDIA hosted inference</div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb">Workspace<ChevronRight size={13}/><strong>{selected ? "Claim review" : view === "admin" ? "Provider operations" : view === "claims" ? "All claims" : "Overview"}</strong></div><div className="account"><span className="avatar">{user.name[0]?.toUpperCase()}</span><span>{user.name}<small>{user.role === "admin" ? "Administrator" : "Claim reviewer"}</small></span><button className="icon-button" aria-label="Sign out" title="Sign out" onClick={() => void logout()}><LogOut size={17}/></button></div></header>
      <main className="main-content">{selected ? <ClaimWorkspace key={selected} id={selected} onBack={() => {setSelected(null); void refresh();}} onChange={() => void refresh()}/> : view === "admin" ? <Admin/> : <>
        <div className="page-heading"><div><span className="eyebrow">EVIDENCE-LED CLAIM REVIEW</span><h1>{view === "claims" ? "Your claims" : `Your claims, in focus.`}</h1><p className="muted">A clear view of your evidence, reviews, and next steps.</p></div><button className="button primary" onClick={() => setNewClaim(true)}><Plus size={17}/>New claim</button></div>
        {error && <div className="notice error" role="alert">{error}<button className="text-button" onClick={() => {setError(""); void refresh();}}>Retry</button></div>}
        {view === "dashboard" && <><div className="stats"><div className="stat panel"><span><FolderOpen size={17}/>Total claims</span><strong>{claims.length}</strong><small>In your workspace</small></div><div className="stat panel"><span><FileCheck2 size={17}/>Ready for review</span><strong>{claims.filter(c => c.status === "ready_for_review").length}</strong><small>Evidence assessment available</small></div><div className="stat panel"><span><Clock3 size={17}/>In review</span><strong>{claims.filter(c => c.status === "in_review").length}</strong><small>Awaiting your next step</small></div><div className="stat panel"><span><CheckCircle2 size={17}/>Reviewed</span><strong>{claims.filter(c => c.status === "reviewed").length}</strong><small>Human review recorded</small></div></div>
          <div className="welcome-panel"><div className="welcome-copy"><span className="eyebrow">FROM DOCUMENTS TO DIRECTION</span><h2>Make your next step an informed one.</h2><p>Collect the evidence. Understand the denial.<br/>Prepare a grounded response.</p><button className="text-button" onClick={() => setNewClaim(true)}>Start a claim<ArrowRight size={15}/></button></div><div className="workflow-visual"><div><FileText/><span>Evidence</span><small>Your documents</small></div><span className="workflow-line"/><div className="highlight"><Sparkles/><span>Intelligence</span><small>Grounded analysis</small></div><span className="workflow-line"/><div><ShieldCheck/><span>Your review</span><small>Your next step</small></div></div></div></>}
        <section className="panel claims-panel"><div className="panel-title"><div><h3>{view === "claims" ? "Claim workspace" : "Recent claims"}</h3><p className="muted small">Keep your evidence and review history together.</p></div><div className="table-controls"><label className="search-box"><Search size={16}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search claims…" aria-label="Search claims"/></label><select value={filter} onChange={e => setFilter(e.target.value)} aria-label="Filter claim status"><option value="all">All statuses</option>{['collecting_evidence','ready_for_review','in_review','reviewed'].map(s => <option value={s} key={s}>{label(s)}</option>)}</select></div></div>
          {filtered.length ? <div className="table-scroll"><table><thead><tr><th>CLAIM</th><th>INSURER</th><th>AMOUNT</th><th>STATUS</th><th>UPDATED</th><th><span className="visually-hidden">Open</span></th></tr></thead><tbody>{filtered.map(claim => <tr key={claim.id}><td><button className="claim-link" onClick={() => setSelected(claim.id)}><span className="file-icon"><FileText size={18}/></span><span><strong>{claim.title}</strong><small>{claim.claim_number || claim.id.slice(0, 8)}</small></span></button></td><td>{claim.insurer || "—"}</td><td className="amount">{money(claim.amount)}</td><td><Badge value={claim.status}/></td><td className="muted">{date(claim.updated_at)}</td><td><button className="icon-button" aria-label={`Open ${claim.title}`} onClick={() => setSelected(claim.id)}><ChevronRight size={17}/></button></td></tr>)}</tbody></table></div> : <div className="empty claims-empty"><div className="empty-icon"><FolderOpen size={34}/></div><h3>{claims.length ? "No matching claims" : "A clearer claim starts here"}</h3><p>{claims.length ? "Try another search or status filter." : "Create your first claim and add the evidence that matters."}</p>{!claims.length && <div className="empty-actions"><button className="button primary" onClick={() => setNewClaim(true)}><Plus size={16}/>Create a claim</button>{demoEnabled && <button className="button secondary" disabled={demoBusy} onClick={() => void demo()}>{demoBusy ? <LoaderCircle className="spin" size={16}/> : <FileText size={16}/>}Try synthetic sample</button>}</div>}</div>}
          {claims.length >= 100 && <p className="muted small centered">Showing the most recent 100 claims.</p>}
        </section><div className="workspace-note"><ShieldCheck size={15}/>Evidence-backed assistance. All findings and appeals require human review.</div>
      </>}</main>
    </div>{newClaim && <NewClaim onClose={() => setNewClaim(false)} onCreated={claim => {setNewClaim(false); void refresh(); setSelected(claim.id);}}/>}
  </div>;
}
