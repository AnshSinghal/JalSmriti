import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { Languages, LogOut, Menu, Moon, ShieldCheck, Sun, User, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { LANGUAGES, useT } from "../lib/i18n";
import { useTheme } from "../lib/theme";
import AuthDialog from "./AuthDialog";

export function Logo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true">
      <rect width="40" height="40" rx="9" fill="rgb(var(--ink))" />
      <path d="M7 26c4-4 6.5-4 10.5 0s6.5 4 10.5 0 5-3.3 5-3.3" fill="none" stroke="rgb(var(--memory-soft))" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M7 16.5h26M7 13v7" stroke="rgb(var(--built))" strokeWidth="2.6" strokeLinecap="round" />
    </svg>
  );
}

function NavItems({ onClick }: { onClick?: () => void }) {
  const { t } = useT();
  const cls = ({ isActive }: { isActive: boolean }) =>
    `tap inline-flex items-center rounded-md px-3 py-2 text-[15px] font-medium transition-colors lg:px-2 xl:px-2.5 2xl:px-3 ${isActive ? "text-ink" : "text-ink-2 hover:text-ink"}`;
  return (
    <>
      <NavLink to="/explore" className={cls} onClick={onClick}>{t("nav.explore")}</NavLink>
      <NavLink to="/place" className={cls} onClick={onClick}>{t("nav.check")}</NavLink>
      <NavLink to="/waterlogging" className={cls} onClick={onClick}>{t("nav.water")}</NavLink>
      <NavLink to="/defend" className={cls} onClick={onClick}>{t("nav.defend")}</NavLink>
      <NavLink to="/about" className={cls} onClick={onClick}>{t("nav.about")}</NavLink>
    </>
  );
}

function LanguageMenu() {
  const { lang, setLang, t } = useT();
  const current = LANGUAGES.find((l) => l.code === lang)?.name ?? "English";
  return (
    <Dropdown.Root>
      <Dropdown.Trigger className="btn-ghost" aria-label={t("nav.language")}>
        <Languages size={18} />
        <span className="hidden text-[15px] sm:inline">{current}</span>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-[10rem] rounded-lg border border-line bg-paper p-1 shadow-xl">
          {LANGUAGES.map((l) => (
            <Dropdown.Item key={l.code} onSelect={() => setLang(l.code)}
              className={`tap flex cursor-pointer items-center rounded-md px-3 py-2 text-[15px] outline-none data-[highlighted]:bg-paper-2 ${l.code === lang ? "font-semibold text-memory" : ""}`}>
              {l.name}
            </Dropdown.Item>
          ))}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

function AccountMenu() {
  const { user, openAuth, signOut } = useAuth();
  const { t } = useT();
  if (!user) {
    return <button className="btn-quiet py-2" onClick={() => openAuth("signin")}>{t("nav.signin")}</button>;
  }
  return (
    <Dropdown.Root>
      <Dropdown.Trigger className="btn-quiet py-2" aria-label={t("nav.account")}>
        <User size={17} />
        <span className="hidden max-w-[10rem] truncate md:inline lg:hidden 2xl:inline">{user.email}</span>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" sideOffset={6} className="z-50 min-w-[13rem] rounded-lg border border-line bg-paper p-1 shadow-xl">
          <Dropdown.Item asChild>
            <Link to="/me" className="flex items-center gap-2 rounded-md px-3 py-2 text-[15px] outline-none data-[highlighted]:bg-paper-2">
              <User size={16} /> {t("nav.account")}
            </Link>
          </Dropdown.Item>
          {user.role !== "citizen" && (
            <Dropdown.Item asChild>
              <Link to="/console" className="flex items-center gap-2 rounded-md px-3 py-2 text-[15px] outline-none data-[highlighted]:bg-paper-2">
                <ShieldCheck size={16} /> {t("nav.console")}
              </Link>
            </Dropdown.Item>
          )}
          <Dropdown.Separator className="my-1 h-px bg-line" />
          <Dropdown.Item onSelect={signOut} className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-[15px] outline-none data-[highlighted]:bg-paper-2">
            <LogOut size={16} /> {t("nav.signout")}
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  );
}

export function Header() {
  const { t } = useT();
  const [theme, setTheme] = useTheme();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper/90 backdrop-blur supports-[backdrop-filter]:bg-paper/75">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:px-6">
        <Link to="/" className="tap flex items-center gap-2.5" aria-label={t("brand.name")}>
          <Logo className="h-9 w-9" />
          <span className="display text-[1.55rem] leading-none">{t("brand.name")}</span>
        </Link>
        <nav className="ml-4 hidden items-center lg:flex"><NavItems /></nav>
        <div className="ml-auto flex items-center gap-1">
          <LanguageMenu />
          <button className="btn-ghost" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? t("nav.themeLight") : t("nav.themeDark")}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <div className="hidden sm:block"><AccountMenu /></div>
          <button className="btn-ghost lg:hidden" onClick={() => setOpen((v) => !v)} aria-label={t("nav.menu")} aria-expanded={open}>
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>
      {open && (
        <div className="border-t border-line bg-paper px-4 pb-4 pt-2 lg:hidden">
          <nav className="flex flex-col"><NavItems onClick={() => setOpen(false)} /></nav>
          <div className="mt-2 sm:hidden"><AccountMenu /></div>
        </div>
      )}
    </header>
  );
}

export function Footer() {
  const { t } = useT();
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto grid max-w-[1400px] gap-8 px-4 py-10 sm:px-6 md:grid-cols-[1.2fr_1fr]">
        <div className="max-w-prose">
          <div className="flex items-center gap-2.5">
            <Logo className="h-8 w-8" />
            <span className="display text-[1.35rem]">{t("brand.name")}</span>
            <span className="muted">{t("brand.tagline")}</span>
          </div>
          <p className="muted mt-3 text-[15px]">{t("footer.note")}</p>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-[15px] md:justify-end">
          <Link className="link tap inline-flex items-center" to="/about">{t("footer.methods")}</Link>
          <Link className="link tap inline-flex items-center" to="/about#data">{t("footer.data")}</Link>
          <Link className="link tap inline-flex items-center" to="/explore">{t("nav.explore")}</Link>
          <Link className="link tap inline-flex items-center" to="/place">{t("nav.check")}</Link>
        </div>
      </div>
    </footer>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-paper focus:px-3 focus:py-2">Skip to content</a>
      <Header />
      <main id="main" className="flex-1">{children}</main>
      <Footer />
      <AuthDialog />
    </div>
  );
}
