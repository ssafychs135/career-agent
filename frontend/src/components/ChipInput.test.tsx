import { render, screen, fireEvent } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import ChipInput from "./ChipInput";

function add(input: HTMLElement, text: string) {
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

test("adds text chip on Enter, dedupes, drops empty", () => {
  const onChange = vi.fn();
  const { rerender } = render(<ChipInput value={[]} onChange={onChange} mode="text" />);
  const input = screen.getByRole("textbox");
  add(input, "  백엔드 ");
  expect(onChange).toHaveBeenLastCalledWith(["백엔드"]);
  rerender(<ChipInput value={["백엔드"]} onChange={onChange} mode="text" />);
  add(input, "백엔드"); // 중복
  expect(onChange).toHaveBeenLastCalledWith(["백엔드"]);
});

test("number mode rejects non-numeric", () => {
  const onChange = vi.fn();
  render(<ChipInput value={[]} onChange={onChange} mode="number" />);
  const input = screen.getByRole("textbox");
  add(input, "abc");
  expect(onChange).not.toHaveBeenCalled();
  add(input, "518");
  expect(onChange).toHaveBeenLastCalledWith([518]);
});

test("removes chip on × click", () => {
  const onChange = vi.fn();
  render(<ChipInput value={["백엔드", "ML"]} onChange={onChange} mode="text" />);
  fireEvent.click(screen.getByLabelText("백엔드 제거"));
  expect(onChange).toHaveBeenLastCalledWith(["ML"]);
});
