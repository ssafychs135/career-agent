/**
 * Spring presets — apple-design §4 (behavior over animation).
 *
 * Motion's `bounce` + `duration` maps to Apple's damping + response:
 *  - bounce 0   ≈ damping 1.0 (critically damped, no overshoot) — the house default
 *  - bounce ~0.2 ≈ damping ~0.8 — reserved for momentum/gesture-driven motion only
 *    (a trigger the user pressed), never for something that merely faded in.
 * `duration` here is the spring "response" (settle emerges from params), not a hard cap.
 */
import type { Transition } from "motion/react";

/** Default UI spring — graceful, non-distracting. Response ~0.4s (§4 table). */
export const SPRING_UI: Transition = { type: "spring", bounce: 0, duration: 0.4 };

/** Snappier settle for small/nav elements. */
export const SPRING_SNAPPY: Transition = { type: "spring", bounce: 0, duration: 0.3 };

/** Momentum — slight overshoot, ONLY after a user-initiated action (§4). */
export const SPRING_MOMENTUM: Transition = { type: "spring", bounce: 0.22, duration: 0.4 };

/** Enter transform: rise + materialize. Pair opacity+translate, compositor-friendly (§11). */
export const riseIn = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: SPRING_UI,
};

/** Stagger children (list rows) — small offset telegraphs order (§16 hierarchy). */
export const stagger = (i: number, step = 0.035): Transition => ({
  ...SPRING_UI,
  delay: i * step,
});
