import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";
import Explorer from "./pages/Explorer";
import Ops from "./pages/Ops";

const active = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

/* Left vertical nav rail — floating translucent chrome (§12), app-wide. */
function Rail() {
  return (
    <nav className="rail">
      <div className="logo" aria-hidden>
        c
      </div>
      <NavLink to="/jobs" title="탐색" className={active}>
        ◱
      </NavLink>
      <NavLink to="/" end title="운영" className={active}>
        ⚙
      </NavLink>
      <span style={{ flex: 1 }} />
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div className="shell">
        <Rail />
        <div className="content">
          <Routes>
            <Route path="/" element={<Ops />} />
            <Route path="/jobs" element={<Explorer />} />
            <Route path="/jobs/:source/:jobId" element={<Explorer />} />
            {/* 옛 라우트 → 운영 대시보드로 통합(북마크 보호) */}
            <Route path="/settings" element={<Navigate to="/" replace />} />
            <Route path="/status" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
