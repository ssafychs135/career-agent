import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Home from "./pages/Home";
import Explorer from "./pages/Explorer";
import Settings from "./pages/Settings";
import Status from "./pages/Status";

const active = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

/* Left vertical nav rail — floating translucent chrome (§12), app-wide. */
function Rail() {
  return (
    <nav className="rail">
      <div className="logo" aria-hidden>
        c
      </div>
      <NavLink to="/" end title="홈" className={active}>
        ⌂
      </NavLink>
      <NavLink to="/jobs" title="탐색" className={active}>
        ◱
      </NavLink>
      <NavLink to="/settings" title="설정" className={active}>
        ⚙
      </NavLink>
      <NavLink to="/status" title="상태" className={active}>
        ◉
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
            <Route path="/" element={<Home />} />
            <Route path="/jobs" element={<Explorer />} />
            <Route path="/jobs/:source/:jobId" element={<Explorer />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/status" element={<Status />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  );
}
