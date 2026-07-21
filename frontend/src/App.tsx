import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  useLocation,
} from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import Home from "./pages/Home";
import JobsList from "./pages/JobsList";
import JobDetail from "./pages/JobDetail";
import { SPRING_UI } from "./design/springs";

/* Translucent floating chrome — content scrolls underneath (§12). */
function Nav() {
  const linkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
    position: "relative",
    padding: "0.35rem 0.1rem",
    fontWeight: 500,
    color: isActive ? "var(--text)" : "var(--text-3)",
    textDecoration: "none",
  });
  return (
    <nav
      className="chrome"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        display: "flex",
        alignItems: "center",
        gap: "1.25rem",
        padding: "0.6rem clamp(1rem, 4vw, 2.5rem)",
      }}
    >
      <span style={{ fontWeight: 600, letterSpacing: "-0.02em", marginRight: "0.5rem" }}>
        career·agent
      </span>
      {/* Direct, specific labels — name items for their contents (§16) */}
      <NavLink to="/" style={linkStyle} end>
        {({ isActive }) => (
          <>
            홈
            {isActive && (
              <motion.span
                layoutId="nav-underline"
                style={underline}
                transition={SPRING_UI}
              />
            )}
          </>
        )}
      </NavLink>
      <NavLink to="/jobs" style={linkStyle}>
        {({ isActive }) => (
          <>
            공고
            {isActive && (
              <motion.span
                layoutId="nav-underline"
                style={underline}
                transition={SPRING_UI}
              />
            )}
          </>
        )}
      </NavLink>
    </nav>
  );
}

const underline: React.CSSProperties = {
  position: "absolute",
  left: 0,
  right: 0,
  bottom: -6,
  height: 2,
  borderRadius: 2,
  background: "var(--accent)",
};

function AnimatedRoutes() {
  const location = useLocation();
  return (
    // §7 spatial consistency: routes enter/leave on the same fade+rise path.
    <AnimatePresence mode="wait">
      <motion.div
        key={location.pathname.startsWith("/jobs/") ? "detail" : location.pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={SPRING_UI}
      >
        <Routes location={location}>
          <Route path="/" element={<Home />} />
          <Route path="/jobs" element={<JobsList />} />
          <Route path="/jobs/:source/:jobId" element={<JobDetail />} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  );
}

export default function App() {
  return (
    // Opt into v7 behavior now — keeps the console pristine (§16 craft).
    <BrowserRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Nav />
      <AnimatedRoutes />
    </BrowserRouter>
  );
}
