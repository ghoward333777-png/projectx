/* QueryBook shared UI: app-wide theme (light/dark) with one persistent toggle on every page.
   Pure vanilla, no dependencies. Safe to load on any page; it only adds a toggle button
   and sets data-theme on <html>. Per-viewer preference is remembered in localStorage. */
(function(){
  var KEY="qb-theme";
  function saved(){ try{ return localStorage.getItem(KEY); }catch(e){ return null; } }
  function sysDark(){ try{ return window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches; }catch(e){ return false; } }
  function apply(mode){
    // mode: "dark" | "light"
    try{ document.documentElement.setAttribute("data-theme", mode); }catch(e){}
    var b=document.getElementById("qb-theme-toggle");
    if(b){ b.textContent = mode==="dark" ? "☀" : "☾";
      b.title = mode==="dark" ? "Switch to light mode" : "Switch to dark mode";
      b.setAttribute("data-tip", b.title); }
  }
  function current(){ return document.documentElement.getAttribute("data-theme")||"light"; }
  // initial theme: saved preference, else follow the OS
  var initial = saved() || (sysDark() ? "dark" : "light");
  try{ document.documentElement.setAttribute("data-theme", initial); }catch(e){}

  function addToggle(){
    // If the page already ships its own theme toggle (same qb-theme key), don't add a second.
    if(document.getElementById("themeBtn")) { apply(current()); return; }
    if(document.getElementById("qb-theme-toggle")) { apply(current()); return; }
    var b=document.createElement("button");
    b.id="qb-theme-toggle"; b.type="button";
    b.setAttribute("aria-label","Toggle light/dark theme");
    b.onclick=function(){
      var next = current()==="dark" ? "light" : "dark";
      apply(next);
      try{ localStorage.setItem(KEY, next); }catch(e){}
    };
    document.body.appendChild(b);
    apply(current());
  }
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", addToggle);
  else addToggle();
})();
