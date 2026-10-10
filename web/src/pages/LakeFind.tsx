import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorNote, Progress } from "../components/bits";
import MapView from "../components/MapView";
import { placeUrl } from "../components/SearchBox";
import { api, ApiError } from "../lib/api";
import { useT } from "../lib/i18n";
import { useJob } from "../lib/queries";

export default function LakeFind() {
  const { t } = useT();
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const lat = Number(sp.get("lat"));
  const lon = Number(sp.get("lon"));
  const valid = !!sp.get("lat") && !!sp.get("lon") && !Number.isNaN(lat) && !Number.isNaN(lon);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const { data: job } = useJob(jobId);

  useEffect(() => {
    if (!valid || started.current) return;
    started.current = true;
    api.post<{ jobId: string }>("/v1/lakes/find", { lat, lon })
      .then((r) => setJobId(r.jobId))
      .catch((e) => setError(e instanceof ApiError && e.status === 400 ? t("place.outside") : e.message));
  }, [valid]);

  const lakeId = job?.result?.lakeId ?? null;
  useEffect(() => {
    if (job?.status === "done" && lakeId) nav(`/lake/${lakeId}`, { replace: true });
    if (job?.status === "failed") setError(job.error ?? "failed");
  }, [job?.status, lakeId]);

  if (!valid) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 py-12 sm:px-6">
        <h1 className="text-[clamp(2.2rem,5vw,3.4rem)]">{t("find.title")}</h1>
        <p className="mt-4 text-[16.5px] text-ink-2">{t("find.missing")}</p>
        <Link className="btn-primary mt-6" to="/place?pick=lake">{t("defend.pointMap")}</Link>
      </div>
    );
  }

  const j = (job ?? {}) as any;
  const none = job?.status === "done" && !lakeId;
  const st = (done: boolean, running: boolean) => (done ? "done" : running ? "running" : "waiting") as "done" | "running" | "waiting";
  const found = !!j.lakeId;
  const steps = [
    { label: t("find.step.find"), state: st(found || job?.status === "done", !found) },
    { label: t("find.step.looks"), state: st(!!j.step_looks, found && !j.step_looks) },
    { label: t("find.step.static"), state: st(!!j.step_static, found && !j.step_static) },
    { label: t("find.step.latest"), state: st(!!j.step_latest, found && !j.step_latest) },
    { label: t("find.step.grade"), state: st(job?.status === "done", !!(j.step_looks && j.step_static && j.step_latest)) },
  ];

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-8 sm:px-6">
      <p className="muted text-[15px]">{lat.toFixed(5)} N, {lon.toFixed(5)} E</p>
      <h1 className="mt-1 text-[clamp(2.1rem,4.6vw,3.4rem)]">{none ? t("lake.noneHere") : t("find.title")}</h1>
      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] [&>*]:min-w-0">
        <div>
          {error ? <ErrorNote>{t("place.failed", { msg: error })}</ErrorNote> : none ? (
            <div className="space-y-4">
              <p className="max-w-prose text-[16.5px] text-ink-2">{job?.result?.why}</p>
              <div className="flex flex-wrap gap-2">
                <Link className="btn-primary" to="/place?pick=lake">{t("find.tryAnother")}</Link>
                <Link className="btn-quiet" to={placeUrl({ lat, lon })}>{t("explore.checkHere")}</Link>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-line p-5">
              <Progress steps={steps} />
              <p className="muted mt-5 text-[14.5px]">{t("find.wait")}</p>
            </div>
          )}
        </div>
        <div className="relative h-[420px] overflow-hidden rounded-xl border border-line">
          <MapView className="absolute inset-0" center={[lon, lat]} zoom={14} marker={[lon, lat]} satellite interactive={false} />
        </div>
      </div>
    </div>
  );
}
