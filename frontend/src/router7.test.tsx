import { render, screen, fireEvent, waitFor, cleanup, act } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { BrowserRouter, Routes, Route, Link, Outlet, useLocation } from "react-router-dom";

function Location() { return <output data-testid="location">{useLocation().pathname}</output>; }
afterEach(cleanup);

test("BrowserRouter commits relative navigation and real history back/forward, including a splat fixture", async () => {
  window.history.replaceState(null, "", "/fixture/parent/child");
  render(<BrowserRouter><Location /><Routes>
    <Route path="fixture" element={<Outlet />}>
      <Route path="parent" element={<Outlet />}>
        <Route path="child" element={<Link to="..">parent</Link>} />
        <Route index element={<Link to="child">child</Link>} />
      </Route>
      <Route path="*" element={<Link to="relative">splat relative</Link>} />
    </Route>
  </Routes></BrowserRouter>);
  fireEvent.click(screen.getByText("parent"));
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/fixture/parent"));
  fireEvent.click(screen.getByText("child"));
  await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/fixture/parent/child"));
  window.history.back();
  await screen.findByText("child");
  expect(window.location.pathname).toBe("/fixture/parent");
  window.history.forward();
  await screen.findByText("parent");
  expect(window.location.pathname).toBe("/fixture/parent/child");
  act(() => {
    window.history.pushState(null, "", "/fixture/a/b");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  fireEvent.click(await screen.findByText("splat relative"));
  await waitFor(() => expect(window.location.pathname).toBe("/fixture/a/b/relative"));
});
