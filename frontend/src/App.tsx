import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import Home from "./pages/Home";
import JobsList from "./pages/JobsList";
import JobDetail from "./pages/JobDetail";

export default function App() {
  return (
    <BrowserRouter>
      <nav style={{ padding: "8px 24px", borderBottom: "1px solid #ddd", fontFamily: "sans-serif" }}>
        <Link to="/">home</Link> · <Link to="/jobs">공고</Link>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/jobs" element={<JobsList />} />
        <Route path="/jobs/:source/:jobId" element={<JobDetail />} />
      </Routes>
    </BrowserRouter>
  );
}
