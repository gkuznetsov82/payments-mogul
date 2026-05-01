import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

// Stub elkjs entirely in the test environment. The bundled file pulls in a
// Web Worker bootstrap that crashes vitest's tinypool. Code paths that
// import this module at runtime are gated by elkAvailable() which returns
// false under VITEST anyway, but the *static* mock prevents the Vite
// transformer from pulling the 700kB bundle into the worker on a stray
// dynamic-import resolution.
vi.mock("elkjs/lib/elk.bundled.js", () => ({
  default: class MockELK {
    layout(g: unknown) {
      return Promise.resolve(g);
    }
  },
}));

// React Flow uses ResizeObserver and DOMRect APIs that jsdom does not provide.
// Polyfills below are the same recipe React Flow's own test docs recommend.

class _ResizeObserverPolyfill {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof window !== "undefined") {
  if (!("ResizeObserver" in window)) {
    (window as unknown as { ResizeObserver: typeof _ResizeObserverPolyfill }).ResizeObserver =
      _ResizeObserverPolyfill;
  }
  if (!("DOMRect" in window)) {
    class _DOMRectPolyfill {
      constructor(public x = 0, public y = 0, public width = 0, public height = 0) {}
      get top() { return this.y; }
      get left() { return this.x; }
      get bottom() { return this.y + this.height; }
      get right() { return this.x + this.width; }
      static fromRect(r?: { x?: number; y?: number; width?: number; height?: number }) {
        return new _DOMRectPolyfill(r?.x, r?.y, r?.width, r?.height);
      }
      toJSON() { return JSON.stringify(this); }
    }
    (window as unknown as { DOMRect: typeof _DOMRectPolyfill }).DOMRect = _DOMRectPolyfill;
  }
}
