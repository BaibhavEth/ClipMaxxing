import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, vi } from "vitest";

vi.mock("motion/react", async () => {
  const React = await import("react");
  const motionProps = new Set([
    "animate",
    "exit",
    "initial",
    "transition",
    "viewport",
    "whileInView",
  ]);
  const mockElement = (tag: string) => {
    const MockMotionElement = React.forwardRef<HTMLElement, Record<string, unknown>>(
      (props, ref) => {
      const domProps = Object.fromEntries(
        Object.entries(props).filter(([name]) => !motionProps.has(name)),
      );
      return React.createElement(tag, { ...domProps, ref });
      },
    );
    MockMotionElement.displayName = `MockMotion(${tag})`;
    return MockMotionElement;
  };

  return {
    AnimatePresence: ({ children }: { children: ReactNode }) => children,
    motion: {
      article: mockElement("article"),
      div: mockElement("div"),
      form: mockElement("form"),
      section: mockElement("section"),
      span: mockElement("span"),
    },
  };
});

afterEach(cleanup);
