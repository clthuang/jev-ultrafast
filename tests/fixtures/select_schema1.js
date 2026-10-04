(({action,page_key,guard}) => {
  const rejected=reason=>({status:'rejected_before_input',reason});
  const cache=window.__jevFast, option=action.option;
  if (!cache || !option || option.document_id!==performance.timeOrigin || option.cache_epoch!==cache.epoch)
    return rejected('Dropdown document or cache changed');
  if (!Number.isInteger(action.node) || option.select_id!==action.node || !Number.isInteger(option.option_id) ||
      !Number.isInteger(option.observed_index) || option.observed_index<0 || option.selected!==false ||
      option.effective_disabled!==false || !Array.isArray(page_key) || !Array.isArray(guard))
    return rejected('Dropdown descriptor is invalid');
  const select=cache.nodes.get(option.select_id), chosen=cache.nodes.get(option.option_id);
  if (!select?.isConnected || select.tagName!=='SELECT' || select.multiple || !chosen?.isConnected ||
      chosen.tagName!=='OPTION' || chosen.closest('select')!==select ||
      select.options[option.observed_index]!==chosen) return rejected('Dropdown option identity changed');
  const disabled=select.matches(':disabled') || chosen.disabled || !!chosen.closest('optgroup[disabled]');
  if (disabled!==option.effective_disabled || chosen.label!==option.label || chosen.value!==option.value ||
      chosen.selected!==option.selected) return rejected('Dropdown option meaning or state changed');
  if (select.closest('[aria-disabled="true"],[aria-hidden="true"],[inert]') ||
      !select.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return rejected('Dropdown is unavailable');
  if (JSON.stringify(cache.pageKey())!==JSON.stringify(page_key) ||
      JSON.stringify(cache.guard(select))!==JSON.stringify(guard)) return rejected('Dropdown page context changed');
  const r=select.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
  if (r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight ||
      !select.contains(document.elementFromPoint(x,y))) return rejected('Dropdown is covered or outside the viewport');
  select.selectedIndex=option.observed_index;
  select.dispatchEvent(new Event('input',{bubbles:true}));
  select.dispatchEvent(new Event('change',{bubbles:true}));
  return {status:'executed',action_id:action.id};
})
