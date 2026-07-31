import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";

const navItems = [
  { to: "/traces", label: "Traces", glyph: "◆" },
  { to: "/datasets", label: "Datasets", glyph: "▤" },
  { to: "/eval-runs", label: "Eval Runs", glyph: "▲" },
  { to: "/trends", label: "Trends", glyph: "∿" },
];

export default function Layout() {
  const navigate = useNavigate();

  function logout() {
    api.clearApiKey();
    navigate("/login");
  }

  return (
    <div className="flex h-screen">
      <aside className="w-56 shrink-0 border-r border-border bg-panel flex flex-col">
        <div className="px-5 py-5 border-b border-border">
          <div className="font-display text-lg font-semibold tracking-tight text-[#E6EDF3]">
            Agent<span className="text-accent">Eval</span>
          </div>
          <div className="text-xs text-muted mt-0.5">evaluation console</div>
        </div>
        <nav className="flex-1 py-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-2.5 text-sm transition-colors border-l-2 ${
                  isActive
                    ? "border-accent text-[#E6EDF3] bg-white/5"
                    : "border-transparent text-muted hover:text-[#E6EDF3] hover:bg-white/[0.02]"
                }`
              }
            >
              <span className="text-accent/80 w-4 text-center">{item.glyph}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-border">
          <button onClick={logout} className="btn-ghost w-full text-xs">
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-base">
        <Outlet />
      </main>
    </div>
  );
}
