"""Friends & Family 10 — activity checks: reading and exploring count without constant clicking.

Drawn only for Friends & Family 10 participants (and owner/tester accounts, as test records) on Explore, on Learn's
World Geography part and on a World Geography quiz round of at least five questions — never on School Learning, Badges,
Rewards or Owner pages, and never for anybody else.

The page script (no iframe; Streamlit custom component v2, like the Explore map) sends a check about once a minute ONLY
while all of this is true:
  * the page is visible and focused (a background tab, a locked phone or another app sends nothing);
  * the person made a real scroll, touch, key press or click within the last pilot_rewards.ENGAGED_SECONDS (events
    created by scripts are ignored; mouse movement alone does not count, so a "mouse jiggler" earns nothing).
Each check reruns only this small fragment, not the page. The database then decides (pilot_record_heartbeat): its own
clock, at most one accepted check per 50 seconds per person (tabs, devices and reruns cannot add up), only within
15 minutes after a meaningful interaction the same day, and at most 150 a day. A check lost to a network interruption is
never replayed later.
"""
from __future__ import annotations

import streamlit as st

from core import pilot_rewards as pr
from core import rewards

from . import rewards_hooks as hooks

JS = r"""
const EVENTS = ["scroll", "wheel", "touchstart", "touchmove", "keydown", "pointerdown"];
function S() {
  return window.__weFF10 || (window.__weFF10 = { lastInput: 0, lastSent: 0, n: 0, timer: null, trig: null, el: null,
                                                 cfg: { interval: 60, engaged: 75 } });
}
function mark(e) { if (e && e.isTrusted === false) return; S().lastInput = Date.now(); }
function listen(doc) {
  if (!doc || doc.__weFF10) return;
  doc.__weFF10 = true;
  EVENTS.forEach(n => doc.addEventListener(n, mark, { capture: true, passive: true }));
}
function listenFrames() {           // same-origin frames (other components) report their input too
  document.querySelectorAll("iframe").forEach(f => { try { listen(f.contentDocument); } catch (e) {} });
}
function tick() {
  const s = S();
  if (!s.el || !s.el.isConnected || !s.trig) return;            // not on an eligible page right now
  listenFrames();
  const now = Date.now();
  if (document.visibilityState !== "visible" || !document.hasFocus()) return;
  if (now - s.lastInput > s.cfg.engaged * 1000) return;         // no real input recently: not counted
  if (now - s.lastSent < s.cfg.interval * 1000) return;
  s.lastSent = now;
  s.n += 1;
  try { s.trig("beat", s.n); } catch (e) {}
}
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const s = S();
  s.trig = setTriggerValue;
  s.el = parentElement;
  s.cfg = { interval: +data.interval || 60, engaged: +data.engaged || 75 };
  listen(document);
  if (!s.timer) s.timer = window.setInterval(tick, 10000);
}
"""
CSS = ".st-key-ff10_activity_box{position:absolute!important;width:0!important;height:0!important;overflow:hidden!important}"


def area(page: str) -> str | None:
    """Which eligible learning area this page is (None: no checks here)."""
    ss = st.session_state
    if page == "Explore":
        return "explore"
    if page == "Learn":
        return None if ss.get("learn_tab") == "school" else "learn"      # School Learning: never (no monetary link)
    if page == "Quiz":
        quiz = ss.get("quiz")
        if quiz and quiz.get("mode") != "daily_replay" and len(quiz.get("questions", [])) >= rewards.MIN_QUIZ_QUESTIONS:
            return "quiz"
    return None


def _on_beat() -> None:
    hooks.beat(st.session_state.get("ff10_activity_area"))


@st.fragment
def _checks() -> None:
    component = st.components.v2.component("we_ff10_activity", js=JS)
    with st.container(key="ff10_activity_box"):
        component(key="ff10_activity", data={"interval": pr.HEARTBEAT_SECONDS, "engaged": pr.ENGAGED_SECONDS},
                  on_beat_change=_on_beat)


def render(page: str) -> None:
    """Called by app.py after the page has been drawn. Draws nothing for everybody who is not taking part."""
    try:
        where = area(page)
        if not where:
            return
        member = hooks.ff10_member()
        if not member or member.get("needs_acceptance") or not hooks.ff10_checks_on():
            return
        st.session_state.ff10_activity_area = where
        st.html(f"<style>{CSS}</style>")
        _checks()
    except Exception:
        pass                      # learning is never interrupted by the checks
