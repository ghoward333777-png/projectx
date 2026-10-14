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

  // --- file:// guard --------------------------------------------------------
  // If a page is opened directly from disk (file://...) instead of through the
  // running server, every /api call fails with "TypeError: Failed to fetch".
  // Detect that and show a clear, clickable banner pointing at the server URL.
  function fileGuard(){
    try{
      if(location.protocol!=="file:") return;
      var name=(location.pathname.split("/").pop()||"").replace(/\.html?$/i,"");
      var path=(!name||name==="home"||name==="index")?"/":("/"+name);
      var port=(window.QB_PORT||"8099");
      var url="http://127.0.0.1:"+port+path;
      var bar=document.createElement("div");
      bar.setAttribute("role","alert");
      bar.style.cssText="position:fixed;left:0;right:0;top:0;z-index:2147483647;"+
        "background:#8a1c1c;color:#fff;font:600 14px/1.5 system-ui,Segoe UI,Arial,sans-serif;"+
        "padding:12px 16px;box-shadow:0 2px 10px rgba(0,0,0,.35);text-align:center";
      bar.innerHTML="You opened this page as a FILE, so it can't reach QueryBook. "+
        "Open it through the running server instead: "+
        "<a href=\""+url+"\" style=\"color:#fff;text-decoration:underline\">"+url+"</a>"+
        " &nbsp;(make sure the QueryBook window is running).";
      function show(){ if(document.body){ document.body.appendChild(bar);
        document.body.style.paddingTop="52px"; } }
      if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",show);
      else show();
    }catch(e){}
  }
  fileGuard();
})();
