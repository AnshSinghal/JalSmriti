import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { Spinner } from "./components/bits";
import Shell from "./components/Shell";
import { AuthProvider } from "./lib/auth";
import { I18nProvider, useT } from "./lib/i18n";
import Landing from "./pages/Landing";

const Explore = lazy(() => import("./pages/Explore"));
const Place = lazy(() => import("./pages/Place"));
const LakePage = lazy(() => import("./pages/Lake"));
const DossierPage = lazy(() => import("./pages/Dossier"));
const Verify = lazy(() => import("./pages/Verify"));
const Console = lazy(() => import("./pages/Console"));
const Account = lazy(() => import("./pages/Account"));
const About = lazy(() => import("./pages/About"));
const Defend = lazy(() => import("./pages/Defend"));
const LakeFind = lazy(() => import("./pages/LakeFind"));
const Waterlogging = lazy(() => import("./pages/Waterlogging"));

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } } });

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

function NotFound() {
  const { t } = useT();
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-24 sm:px-6">
      <h1>{t("common.notFound")}</h1>
      <a href="/" className="btn-primary mt-8">{t("common.home")}</a>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <I18nProvider>
        <AuthProvider>
          <BrowserRouter>
            <ScrollTop />
            <Shell>
              <Suspense fallback={<div className="mx-auto max-w-[1400px] px-6 py-16"><Spinner /></div>}>
                <Routes>
                  <Route path="/" element={<Landing />} />
                  <Route path="/explore" element={<Explore />} />
                  <Route path="/explore/:areaId" element={<Explore />} />
                  <Route path="/place" element={<Place />} />
                  <Route path="/waterlogging" element={<Waterlogging />} />
                  <Route path="/lake/find" element={<LakeFind />} />
                  <Route path="/lake/:lakeId" element={<LakePage />} />
                  <Route path="/dossier/:id" element={<DossierPage />} />
                  <Route path="/verify/:id" element={<Verify />} />
                  <Route path="/console" element={<Console />} />
                  <Route path="/me" element={<Account />} />
                  <Route path="/about" element={<About />} />
                  <Route path="/defend" element={<Defend />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </Shell>
          </BrowserRouter>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
