"""Optional relaxing background music on the Quiz page.

* Off by default. The choice (on/off) is saved with the profile, like the sound effects.
* Original music made in the browser while it plays (slow chords and soft bell notes through the Web Audio API): no
  audio file to download, no third-party recordings or melodies, and nothing for the server to send.
* ONE player per browser tab. The player script is installed once (window.__weMusic) and kept outside Streamlit's
  redraws, so reruns, Next and moving between questions never restart it and can never stack a second player.
* What the player follows is a small marker that is on the Quiz page only (data-on = the player's choice). The
  player plays only while the marker is present, the choice is on and the tab is visible: leaving the Quiz page,
  switching tabs or putting the app in the background fades it out at once, and it resumes when the player returns.
* Browser autoplay rules are respected: sound starts only after the player has interacted with the page (the click
  on the switch itself counts). A returning player who left music on hears it from their first tap or key press.
* The existing answer sounds (ui/sound.py) are separate and unchanged.

No "<" anywhere in the script: the HTML cleaner drops scripts containing "<" followed by a letter or digit.
"""
from __future__ import annotations

import streamlit as st

VOLUME = 0.05   # master level: quiet, under the answer sounds

PLAYER = """<script data-we-music="1">(function(){
var W=window;if(W.__weMusic){W.__weMusic.poll();return;}
var M={ctx:null,master:null,bus:null,timers:[],playing:false,pref:false,onQuiz:false,lastMarker:null,step:0,resuming:false,sus:0};
W.__weMusic=M;
var VOL=%VOLUME%;
var CH=[[130.81,329.63,392.0,493.88],[110.0,261.63,329.63,392.0],[87.31,261.63,349.23,440.0],[98.0,246.94,293.66,392.0]];
var BE=[[523.25,659.25,783.99],[440.0,523.25,659.25],[523.25,698.46,880.0],[587.33,783.99,493.88]];
function active(){var u=navigator.userActivation;return !u||u.hasBeenActive;}
function audio(){if(M.ctx)return M.ctx;var AC=W.AudioContext||W.webkitAudioContext;if(!AC)return null;
 try{var c=new AC(),g=c.createGain(),lp=c.createBiquadFilter();g.gain.value=0;lp.type='lowpass';lp.frequency.value=1100;lp.Q.value=0.4;
 lp.connect(g);g.connect(c.destination);M.ctx=c;M.master=g;M.bus=lp;}catch(e){return null;}return M.ctx;}
function chord(){var c=M.ctx,t=c.currentTime,ch=CH[M.step%4];M.step+=1;
 ch.forEach(function(f,i){var o=c.createOscillator(),g=c.createGain(),p=i===0?0.32:0.16;o.type=i===0?'triangle':'sine';
 o.frequency.value=f;o.detune.value=i%2?5:-5;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(p,t+2.8);
 g.gain.setValueAtTime(p,t+6.5);g.gain.linearRampToValueAtTime(0,t+10);o.connect(g);g.connect(M.bus);o.start(t);o.stop(t+10.2);});}
function bell(){if(!M.playing||Math.random()>0.6)return;var c=M.ctx,t=c.currentTime,n=BE[(M.step+3)%4];
 var o=c.createOscillator(),g=c.createGain();o.type='sine';o.frequency.value=n[Math.floor(Math.random()*n.length)];
 g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(0.07,t+0.03);g.gain.exponentialRampToValueAtTime(0.0001,t+3.2);
 o.connect(g);g.connect(M.bus);o.start(t);o.stop(t+3.3);}
function want(){return M.pref&&M.onQuiz&&!document.hidden;}
function begin(){if(M.playing||!want()||!M.ctx||M.ctx.state!=='running')return;clearTimeout(M.sus);M.playing=true;
 var g=M.master.gain,t=M.ctx.currentTime;g.cancelScheduledValues(t);g.setValueAtTime(g.value,t);g.linearRampToValueAtTime(VOL,t+2.5);
 chord();M.timers=[setInterval(chord,8000),setInterval(bell,2700)];}
function start(){if(M.playing)return;if(!M.ctx&&!active())return;var c=audio();if(!c)return;
 if(c.state==='running'){begin();return;}if(!active()||M.resuming)return;M.resuming=true;
 c.resume().then(function(){M.resuming=false;begin();},function(){M.resuming=false;});}
function stop(fast){M.timers.forEach(clearInterval);M.timers=[];if(!M.playing)return;M.playing=false;
 var c=M.ctx,g=M.master.gain,t=c.currentTime;g.cancelScheduledValues(t);g.setValueAtTime(g.value,t);g.linearRampToValueAtTime(0,t+(fast?0.12:0.5));
 clearTimeout(M.sus);M.sus=setTimeout(function(){if(!M.playing&&c.state==='running')c.suspend();},fast?200:700);}
M.poll=function(){var m=document.querySelector('.we-music-marker');M.onQuiz=!!m;
 if(m){var v=m.getAttribute('data-on');if(v!==M.lastMarker){M.lastMarker=v;M.pref=v==='1';}}else{M.lastMarker=null;}
 if(want())start();else stop(document.hidden||!M.onQuiz);};
M.setPref=function(on){M.pref=!!on;M.poll();};
M.state=function(){return {playing:M.playing,pref:M.pref,onQuiz:M.onQuiz,ctx:M.ctx?M.ctx.state:'none',players:document.querySelectorAll('script[data-we-music]').length};};
function unlock(e){var t=e.target,sw=t&&t.closest&&t.closest('[class*="st-key-music_switch"]');
 if(sw||want()){var c=audio();if(c&&c.state!=='running'&&!M.resuming){M.resuming=true;c.resume().then(function(){M.resuming=false;M.poll();},function(){M.resuming=false;});}}}
document.addEventListener('pointerdown',unlock,true);document.addEventListener('keydown',unlock,true);
document.addEventListener('visibilitychange',M.poll);W.addEventListener('pagehide',function(){stop(true);});
document.addEventListener('click',function(e){var b=e.target&&e.target.closest&&e.target.closest('.we-pop-close');if(!b)return;
 var trig=document.querySelector('.st-key-quiz_settings_menu button');if(trig){trig.click();trig.focus();}});
setInterval(M.poll,250);M.poll();
})();</script>""".replace("%VOLUME%", str(VOLUME))


def enabled() -> bool:
    return bool(st.session_state.get("music_on", False))


def player() -> None:
    """The Quiz page's marker plus the (once-installed) player. One element, hidden by CSS."""
    st.html(f'<span class="we-music-marker" data-on="{1 if enabled() else 0}"></span>' + PLAYER,
            unsafe_allow_javascript=True)


def tell_player(on: bool, token: int) -> None:
    """Right after the switch changes (a partial redraw): pass the new choice to the player at once."""
    st.html(f"<script data-we-music-pref=\"1\">/*{int(token)}*/window.__weMusic&&window.__weMusic.setPref({'true' if on else 'false'});</script>",
            unsafe_allow_javascript=True)
