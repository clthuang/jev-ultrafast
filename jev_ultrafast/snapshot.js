(() => {
  // Snapshot schema 2: the page keeps the latest observation's exact baseline; only a small token crosses CDP.
  // observe() is the only writer of the baseline; fresh(), target() and select() read it and never replace it.
  const SCHEMA = 2, MAX_BYTES = 262144, MAX_TARGETS = 250, SCOPE_CHARACTERS = 6000, TEXT_CHARACTERS = 6000;
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  // Weak identity only: a node keeps its number while it lives, and nothing here keeps a node alive.
  const id = (cache,e) => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    return cache.ids.get(e);
  };
  const pageKey = cache => [performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[id(cache,e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly,
        e.tagName==='SELECT' && e.multiple ? [...e.selectedOptions].map(o=>[id(cache,o),o.label,o.value]) : null])];
  // A guard's fields, and its scope's text read once per scope per evaluation (memo maps scope node to text).
  const guard = (cache,e,memo,stats) => {
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    if (scope && !memo.has(scope)) {
      memo.set(scope,scope.innerText?.slice(0,SCOPE_CHARACTERS)||'');
      if (stats) stats.scope_reads++;
    }
    if (stats) stats.guard_builds++;
    return [JSON.stringify([id(cache,e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),e.getAttribute('aria-expanded'),
      e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),e.getAttribute('href')]),
      scope ? memo.get(scope) : ''];
  };
  // One pass over the document, shared by observe and fresh: every candidate action, multi-select evidence,
  // visible text and scroll height, with a local id-to-node map for the nodes observe may offer.
  const scan = cache => {
    const actions=[], evidence=[], local=new Map();
    for (const e of document.querySelectorAll(selector)) {
      if (e.tagName!=='SELECT' && e.closest('select')) continue;
      if (!safe(e) || !visible(e)) continue;
      const multiple=e.tagName==='SELECT' && e.multiple;
      if (!multiple && (e.matches(':disabled') || e.closest('[aria-disabled="true"]'))) continue;
      const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
      if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
      if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
      const node=id(cache,e);
      local.set(node,e);
      const base={node,role:rname,label:name(e)||rname,rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
      for (const key of ['checked','selected','expanded']) {
        const value=e.getAttribute('aria-'+key);
        if (value!==null) base[key]=value;
      }
      if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
      if (e.tagName==='SELECT') {
        const selected_options=[...e.selectedOptions].map(o=>({label:o.label,value:o.value}));
        const current_value=selected_options.map(o=>o.label).join(', ');
        if (multiple) {
          evidence.push({...base,multiple:true,selected_options,value:current_value});
          continue;
        }
        for (const [observed_index,o] of [...e.options].entries()) {
          const effective_disabled=e.matches(':disabled') || o.disabled || !!o.closest('optgroup[disabled]');
          if (!o.selected && !effective_disabled) {
            const option_id=id(cache,o);
            local.set(option_id,o);
            actions.push({...base,kind:'select',value:o.value,current_value,label:base.label+' → '+o.label,
              option:{select_id:node,option_id,observed_index,label:o.label,value:o.value,
                selected:o.selected,effective_disabled}});
          }
        }
      } else {
        const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
          (['textbox','searchbox','spinbutton'].includes(rname) ||
            (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
        const value='value' in e ? String(e.value) :
          e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
        actions.push({...base,kind:editable?'fill':'click',value});
        if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
      }
    }
    const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    const range=document.createRange(); let text,length=0;
    while ((text=walker.nextNode()) && length<TEXT_CHARACTERS) {
      const value=text.textContent.trim(), parent=text.parentElement;
      if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(text); const r=range.getBoundingClientRect();
      if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
        words.push(value); length+=value.length;
      }
    }
    return {actions,evidence,local,text:words.join('\n').slice(0,TEXT_CHARACTERS),
      height:document.documentElement.scrollHeight};
  };
  // Exact global semantics: every candidate (offered or omitted, without geometry), evidence and form state.
  const marker = (cache,found,key) => JSON.stringify([performance.timeOrigin,location.href,scrollX,scrollY,
    innerWidth,innerHeight,document.title,found.text,found.actions.map(({rect,...action})=>action),
    found.evidence.map(({rect,...item})=>item),key[6]]);
  const cacheOf = () => window.__jevFast?.schema===SCHEMA ? window.__jevFast : null;
  const current = token => {
    const cache=cacheOf(), base=cache?.baseline;
    if (!base || !token || token.schema!==SCHEMA || token.epoch!==cache.epoch || token.generation!==cache.generation ||
        token.document_id!==performance.timeOrigin) return {cache,base:null};
    return {cache,base};
  };
  // The offered action exactly as observe returned it, and its retained node.
  const reference = (cache,base,action) => {
    if (!action || typeof action.id!=='string' || base.offered.get(action.id)!==JSON.stringify(action)) return null;
    const e=cache.nodes.get(action.node);
    return e?.isConnected ? e : null;
  };
  const scoped = (cache,base,e) => {
    if (JSON.stringify(pageKey(cache))!==base.pageKey) return false;
    const recorded=base.guards.get(cache.ids.get(e)), now=guard(cache,e,new Map(),null);
    return !!recorded && !!now && now[0]===recorded[0] && now[1]===base.scopes[recorded[1]];
  };
  return {
    observe(limits={}) {
      if (!document.body) return null;
      const maxBytes=limits.max_bytes ?? MAX_BYTES, maxTargets=limits.max_targets ?? MAX_TARGETS;
      if (window.__jevFast?.schema!==SCHEMA)
        window.__jevFast={schema:SCHEMA,ids:new WeakMap(),next:1,nodes:new Map(),generation:0,baseline:null,
          overflow:null,epoch:[...crypto.getRandomValues(new Uint32Array(4))].join('-')};
      const cache=window.__jevFast, found=scan(cache), key=pageKey(cache);
      const global=marker(cache,found,key);
      const stats={candidates:found.actions.length,guard_builds:0,scope_reads:0,references:0};
      const offered=found.actions.slice(0,maxTargets);
      offered.forEach((a,i)=>a.id='e'+(i+1));
      const actions=[...offered];
      if (scrollY+innerHeight<found.height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
      if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
      actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
      // Guards and strong references only for what is offered; each distinct scope's text is read once.
      const memo=new Map(), guards=new Map(), scopes=[], scopeIndex=new Map(), nodes=new Map();
      for (const a of offered) {
        nodes.set(a.node,found.local.get(a.node));
        if (a.option) nodes.set(a.option.option_id,found.local.get(a.option.option_id));
        if (guards.has(a.node)) continue;
        const g=guard(cache,found.local.get(a.node),memo,stats);
        if (!g) continue;
        if (!scopeIndex.has(g[1])) { scopeIndex.set(g[1],scopes.length); scopes.push(g[1]); }
        guards.set(a.node,[g[0],scopeIndex.get(g[1])]);
      }
      stats.references=nodes.size;
      const generation=cache.generation+1;
      const token={schema:SCHEMA,epoch:cache.epoch,generation,document_id:performance.timeOrigin};
      const response={snapshot_schema:SCHEMA,observation_token:token,url:location.href,title:document.title,
        w:innerWidth,h:innerHeight,text:found.text,scroll:{y:scrollY,height:found.height},actions,
        evidence:found.evidence,omitted_actions:Math.max(0,found.actions.length-maxTargets),snapshot_stats:stats};
      // Measure the exact UTF-8 reply in a bounded buffer: an overflow never builds an unbounded copy.
      const serialized=JSON.stringify(response), buffer=new Uint8Array(maxBytes+1);
      const {read,written}=new TextEncoder().encodeInto(serialized,buffer);
      cache.generation=generation;
      if (read<serialized.length || written>maxBytes) {
        cache.baseline=null; cache.nodes=new Map(); cache.overflow={generation};
        return {snapshot_schema:SCHEMA,snapshot_too_large:{limit:maxBytes,characters:serialized.length,
          candidates:found.actions.length,omitted_actions:response.omitted_actions,evidence:found.evidence.length,
          text_characters:found.text.length}};
      }
      cache.baseline={token,global,pageKey:JSON.stringify(key),guards,scopes,
        offered:new Map(offered.map(a=>[a.id,JSON.stringify(a)]))};
      cache.nodes=nodes; cache.overflow=null;
      return response;
    },
    fresh(token,action) {
      const {cache,base}=current(token);
      if (!base) return cache?.overflow ? {status:'snapshot_too_large'} : false;
      if (action && (action.kind==='click' || action.kind==='select')) {
        const e=reference(cache,base,action);
        return !!e && scoped(cache,base,e);
      }
      return marker(cache,scan(cache),pageKey(cache))===base.global;
    },
    target(token,action) {
      // Current geometry and hit test for a CLICK or fill; null when stale, unavailable or not offered.
      const {cache,base}=current(token);
      const e=base ? reference(cache,base,action) : null;
      if (!e || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
          !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
      if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
      const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
      if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
      const hit=document.elementFromPoint(x,y);
      if (!e.contains(hit)) return hit ? {covered:hit.localName.slice(0,40)} : null;
      return {x,y};
    },
    select({action,token}) {
      // One synchronous task validates and mutates. No await, retry or value-based fallback.
      const rejected=reason=>({status:'rejected_before_input',reason});
      const {cache,base}=current(token);
      if (!base) return cache?.overflow ? {status:'snapshot_too_large'} : rejected('Dropdown document or cache changed');
      const option=action?.option;
      if (!option || action.kind!=='select' || !Number.isInteger(action.node) || option.select_id!==action.node ||
          !Number.isInteger(option.option_id) || !Number.isInteger(option.observed_index) ||
          option.observed_index<0 || option.selected!==false || option.effective_disabled!==false ||
          base.offered.get(action.id)!==JSON.stringify(action)) return rejected('Dropdown descriptor is invalid');
      const select=cache.nodes.get(option.select_id), chosen=cache.nodes.get(option.option_id);
      if (!select?.isConnected || select.tagName!=='SELECT' || select.multiple || !chosen?.isConnected ||
          chosen.tagName!=='OPTION' || chosen.closest('select')!==select ||
          select.options[option.observed_index]!==chosen) return rejected('Dropdown option identity changed');
      const disabled=select.matches(':disabled') || chosen.disabled || !!chosen.closest('optgroup[disabled]');
      if (disabled!==option.effective_disabled || chosen.label!==option.label || chosen.value!==option.value ||
          chosen.selected!==option.selected) return rejected('Dropdown option meaning or state changed');
      if (select.closest('[aria-disabled="true"],[aria-hidden="true"],[inert]') ||
          !select.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return rejected('Dropdown is unavailable');
      if (!scoped(cache,base,select)) return rejected('Dropdown page context changed');
      const r=select.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
      if (r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight ||
          !select.contains(document.elementFromPoint(x,y))) return rejected('Dropdown is covered or outside the viewport');
      select.selectedIndex=option.observed_index;
      select.dispatchEvent(new Event('input',{bubbles:true}));
      select.dispatchEvent(new Event('change',{bubbles:true}));
      return {status:'executed',action_id:action.id};
    },
  };
})()
