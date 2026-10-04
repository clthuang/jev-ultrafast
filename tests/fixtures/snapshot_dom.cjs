// Dense DOM adapter for exact production snapshot scans. Native tests independently cover Chrome.
module.exports=function(config={}) {
  const dom=require('./select_dom.cjs')();
  if (!config.count) return dom;
  let scopeReads=0;
  Object.defineProperty(dom.form,'innerText',{get(){scopeReads++;return 'Context '.repeat(900)},configurable:true});
  dom.controls=Array.from({length:config.count},(_,index)=>({
    tagName:'BUTTON',type:'button',isConnected:true,labels:[],parentElement:dom.form,value:'',
    label:config.long_label ? '含義'.repeat(1200) : 'Button '+index,
    getAttribute(key){return key==='aria-label'?this.label:null},
    closest(selector){return selector.startsWith('form,') ? dom.form : null},
    checkVisibility(){return true},matches(){return false},
    getBoundingClientRect(){return {x:(index%100)*10,y:Math.floor(index/100)*10,width:8,height:8}},
  }));
  dom.field.getBoundingClientRect=()=>({x:-1000,y:-1000,width:20,height:20});
  dom.document.querySelectorAll=selector=>selector==='input,textarea,select' ? [dom.field] : [...dom.controls,dom.field];
  dom.scopeReads=()=>scopeReads;
  return dom;
};
