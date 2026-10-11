export type Corners = [number, number][];

export type AreaStats = {
  lakes: number; rivers: number; historicHa: number; lostHa: number; builtOverHa: number;
  grades: Record<string, number>; rain?: Record<string, number>; latestDate?: string;
};
export type AreaEvent = { date: string; title: string; detail: string };
export type Area = {
  id: string; names: Record<string, string>; country: string; state: string; lang: string; bbox: number[];
  center: [number, number]; zoom: number; events: AreaEvent[]; story: string; flood2026: boolean;
  status?: string; stage?: string; stats?: AreaStats; manifest?: string;
};
export type Frame = { season: number | "latest"; date: string; source: "LS" | "S2"; platform?: string; url: string; corners: Corners; resM: number };
export type MemoryLayer = { url: string; corners: Corners; legend: Record<string, string>; historicHa: number; lostHa: number; builtOverHa: number };
export type RadarEvent = AreaEvent & { sceneDate: string; sceneId: string; url: string; corners: Corners; unusualHa: number; baselineScenes: number };
export type AreaManifest = Area & {
  stats: AreaStats; frames: Frame[]; layers: { memory?: MemoryLayer }; radarEvents: RadarEvent[]; lakesUrl: string; updatedAt: string;
};
export type LakeRow = {
  lakeId: string; name: string; kind: string; areaHa: number; lon: number; lat: number; grade?: string | null;
  score?: number | null; lostPct?: number | null; lostHa?: number | null; builtPct?: number | null; builtHa?: number | null;
  retention?: number | null; weedPct?: number | null;
};
export type Finding = { key: string; severity: "high" | "medium" | "low" | "info"; text: string; vars?: Record<string, any> };
export type SeasonPoint = { season: number; waterHa: number; date: string; source: "LS" | "S2"; looks: number; rainMm?: number | null };
export type LakeMetrics = {
  historicHa: number; typicalHa: number; permanentHa: number; seasonalHa: number; lostHa: number; lostPct?: number | null;
  newHa: number; meanOccurrence?: number | null; builtByYear: Record<string, number>; builtHa?: number | null;
  builtPct?: number | null; builtChangeHa?: number | null; worldcoverBuiltHa?: number | null; replacedBy: Record<string, number>;
  storageLost: { millionLitresLow: number; millionLitresHigh: number; olympicPoolsLow: number; olympicPoolsHigh: number };
  series: SeasonPoint[]; peakWaterHa?: number | null; recentWaterHa?: number | null;
  retention: { ratio: number | null; pairs?: { season: number; waterHa: number; rainMm?: number; comparedWith: number[]; comparableRain: boolean; thenWaterHa: number }[]; why?: string };
  quality: null | { date: string; openWaterHa: number; weedHa: number; weedPct?: number | null; ndci?: number | null; algaeSign: boolean; dryNow: boolean };
  grade: { grade: string | null; score: number | null; parts: { key: string; points: number; label: string }[] };
};
export type Authority = { id: string; kind: string; name: string; url?: string; how?: string };
export type Lake = {
  lakeId: string; areaId: string; name: string; nameSource?: string; admin?: Record<string, string>; kind: string;
  areaHa: number; lon: number; lat: number; geometry: GeoJSON.Geometry; metrics: LakeMetrics; findings: Finding[];
  frames: (number | "latest")[]; frameUrls: Record<string, string>; latestDate?: string; area: Area | null;
  authorities: Authority[]; laws: string[]; watchers: number; evidenceCount?: number; onDemand?: boolean; updatedAt?: string;
  insights?: LakeInsights;
};
export type Cause = { key: "encroachment" | "drying" | "overgrown" | "inflow" | "sewage" | "holding"; severity: "high" | "medium" | "low"; vars: Record<string, any>; text: string };
export type LakeInsights = {
  causes: Cause[];
  actions: { residents: string[]; authorities: string[] };
  benefit: null | { lostHa: number; millionLitresLow: number; millionLitresHigh: number; poolsLow: number; poolsHigh: number };
};
export type NewsArticle = { title: string; url: string; domain: string; date: string | null; language?: string; country?: string; tags: string[] };
export type News = {
  status: "ok" | "stale" | "unavailable" | "none"; query: string | null; articles: NewsArticle[]; fetchedAt?: string | null;
  window: string; source: string; kind: string; reason?: string; tags: Record<string, number>; locality?: string;
};
export type Evidence = {
  evidenceId: string; lakeId: string; areaId?: string; status: string; createdAt: string; capturedAt?: string;
  url?: string; thumbUrl?: string; categories?: string[]; gpsCheck?: string; gpsDistanceM?: number; sha256?: string;
  uploader?: string; note?: string; review?: { decision: string; by: string; role: string; at: string; note: string };
  facesBlurred?: number; ai?: { summary?: string; categories?: string[]; confidence?: number; model?: string }; camera?: string;
  width?: number; height?: number; lakeName?: string;
};
export type TimelineEntry = { at: string; status: string; by: string; role?: string; note?: string };
export type Dossier = {
  dossierId: string; lakeId: string; areaId?: string; lakeName?: string; status: string; createdAt: string; readyAt?: string;
  creator?: string; recipient?: Authority; language?: string; pdfUrl?: string; payloadSha256?: string; pdfSha256?: string;
  timeline?: TimelineEntry[]; letter?: { subject: string; body: string; asks?: string[]; model?: string };
  translation?: { subject?: string; body?: string; asks?: string[]; engine?: string; languageName?: string; error?: string } | null;
  facts?: Record<string, any>; submission?: { portal: string; reference: string; at: string }; error?: string;
};
export type PlaceSignals = Record<string, any>;
export type PlaceFrame = { season: number; date: string; source: "LS" | "S2"; platform?: string; url: string; waterShare300: number };
export type Action = { key: string; vars?: Record<string, any> };
export type PlaceActions = { home: Action[]; resident: Action[] };
export type Heat = {
  hereC: number | null; builtC?: number | null; waterC?: number | null; treesC?: number | null; vsBuiltC?: number | null;
  vsWaterC?: number | null; hotter?: boolean | null; years?: number[]; scale?: [number, number]; imageUrl?: string;
  corners?: Corners; error?: string; scenes?: { date: string; platform: string }[];
};
export type PlaceResult = {
  lat: number; lon: number; label?: { label?: string; locality?: string; city?: string; state?: string; country?: string };
  areaId?: string | null; signals: PlaceSignals; memory: { index: number | null; tier: string; ranks: Record<string, number>; radarSightings: number };
  findings: Finding[]; frames: PlaceFrame[]; radar: { scenesChecked?: number; years?: number[]; usualWaterHa?: number; error?: string };
  heat?: Heat | null; actions?: PlaceActions; country?: string; scienceVersion: string; checkedAt: string; checkId: string;
};
export type ForecastDay = { date: string; mm: number; prob?: number | null; maxHourlyMm: number; level: string };
export type Forecast = { days: ForecastDay[]; next24hMm: number; maxHourlyMm: number; timezone: string; source: string; fetchedAt: string };
export type PlaceReport = { reportId: string; status: "rendering" | "ready" | "failed"; pdfUrl?: string; lang?: string; persona?: string; label?: string; error?: string };
export type WaterReport = {
  reportId: string; lat: number; lon: number; seenAt: string; createdAt: string; capturedAt?: string; depth?: string;
  ai?: { waterVisible?: boolean | null; depth?: string | null; summary?: string | null; confidence?: number | null; model?: string };
  status: string; url?: string; thumbUrl?: string; uploader?: string; areaId?: string; note?: string;
  review?: { decision: string; by: string; role: string; at: string; note: string };
  locationSource?: string; oldPhoto?: boolean; locationMismatch?: boolean; hiddenReason?: "text" | "no-water";
};
export type Nearby = { count: number; radiusM: number; days: number; items: WaterReport[]; lastSeenAt?: string | null };
export type RtiRequest = {
  rtiId: string; lakeId: string; lakeName?: string; office: string; filedOn: string; dueBy: string; reference?: string;
  channel?: string; items?: string[]; by?: string; createdAt: string; ledgerSeq?: number; country?: string;
};
export type Follow = { gh7: string; lat: number; lon: number; label?: string; tier?: string; createdAt?: string; lastAlertFor?: string };
export type Activity = {
  evidence: Evidence[]; dossiers: Dossier[]; watches: { lakeId: string; lakeName?: string; status?: string; createdAt?: string }[];
  follows: Follow[]; headsUp: { status: string } | null; waterReports: WaterReport[]; rti: RtiRequest[];
};
export type Job = {
  type: "place" | "lake"; status: "running" | "done" | "failed"; lat: number; lon: number; createdAt: string; stage?: string;
  static?: { signals: PlaceSignals; areaId?: string; label?: PlaceResult["label"] }; optical?: { frames: PlaceFrame[] }; heat?: Heat;
  radar?: { sightings: { date: string; orbit: number; haCore: number; haGrid: number }[]; scenesChecked: number };
  result?: any; error?: string; lakeId?: string;
};
export type Me = {
  user: { id: string; username?: string; role: "citizen" | "verifier" | "officer" | "admin"; jurisdictions: string[]; pseudonym: string; email?: string; groups: string[] };
  consoleAreas: string[];
};
export type VerifyResult = {
  kind?: "dossier" | "report"; dossierId?: string; reportId?: string; lakeId?: string; lakeName?: string; status: string;
  subject?: string; lat?: number; lon?: number; lang?: string;
  attestation: { dossierId?: string; reportId?: string; kind?: string; payloadSha256: string; pdfSha256: string; signedAt: string; keyFingerprint: string; issuer: string };
  attestationCanonical: string; signature: { alg: string; raw: string; der: string };
  publicKey: { spki: string; fingerprint: string; local: boolean }; serverCheck: boolean; pdfUrl?: string;
  payloadSha256?: string; pdfSha256?: string; ledger?: { ok: boolean; entries: number; brokenAt?: number };
  timeline?: TimelineEntry[]; createdAt?: string; creator?: string;
};
export type AuditEntry = {
  SK: string; action: string; pseudonym?: string; role?: string; resource?: { type: string; id: string }; allowed: boolean;
  explanation?: string; policies?: string[]; extra?: any;
};
