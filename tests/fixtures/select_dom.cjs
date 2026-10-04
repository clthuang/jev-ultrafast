// Small DOM adapter: production snapshot.js and atomic SELECT code execute unchanged against these nodes.
module.exports = function createDOM(config = {}) {
  global.window = global;
  global.performance = {timeOrigin: 123456};
  global.crypto = require('node:crypto').webcrypto;
  global.innerWidth = 1120; global.innerHeight = 780; global.scrollX = 0; global.scrollY = 0;
  global.NodeFilter = {SHOW_TEXT: 4};
  global.Event = class {constructor(type) {this.type = type}};
  const events = [], form = {innerText:'Choose a category', isConnected:true};
  const select = {
    tagName:'SELECT', isConnected:true, multiple:!!config.multiple, disabled:!!config.disabled,
    readOnly:false, parentElement:form, labels:[], hidden:false, ariaDisabled:false,
    getAttribute(name) {return name==='aria-label' ? 'Category' : null},
    checkVisibility() {return !this.hidden},
    matches(selector) {return selector===':disabled' && (this.disabled || this.fieldsetDisabled)},
    closest(selector) {
      if (selector==='select') return this;
      if (selector.includes('aria-disabled') && this.ariaDisabled) return this;
      if (selector.startsWith('form,')) return form;
      return null;
    },
    contains(node) {return node===this || this.options.includes(node)},
    getBoundingClientRect() {return {x:10,y:10,width:180,height:35}},
    dispatchEvent(event) {events.push({event:event.type,index:this.selectedIndex,key:this.selectedOptions[0]?.key})},
    get selectedOptions() {return this.options.filter(option=>option.selected)},
    get selectedIndex() {return this.options.findIndex(option=>option.selected)},
    set selectedIndex(index) {this.options.forEach((option,i)=>option.selected = i===index)},
    get value() {return this.selectedOptions[0]?.value ?? ''},
    set value(value) {this.selectedIndex=this.options.findIndex(option=>option.value===value)},
  };
  const group = {disabled:false};
  const options = [
    ['placeholder','', 'Choose',true,false], ['disabled-alias','same','Same',false,true],
    ['first','same','Same',false,false], ['second','same','Same',false,false],
    ['other','other','Other',false,false],
  ].map(([key,value,label,selected,disabled],index)=>({
    key,value,label,selected,disabled,tagName:'OPTION',isConnected:true,owner:select,
    group:index>=3 ? group : null,role:config.multiple && index>=2 ? 'option' : null,
    closest(selector) {
      if(selector==='select') return this.owner;
      if(selector==='optgroup[disabled]') return this.group?.disabled ? this.group : null;
      return null;
    },
  }));
  select.options=options;
  if(config.multiple) {options[0].selected=false;options[2].selected=options[3].selected=true}
  const field={...select,tagName:'INPUT',type:'text',multiple:false,value:'old',checked:false,
    options:[],labels:[],getAttribute:name=>name==='aria-label'?'Query':null,
    closest(selector) {return selector.startsWith('form,') ? form : null}};
  const document = global.document = {
    body:{},title:'Fixture',documentElement:{scrollHeight:780},covered:false,
    querySelectorAll(selector) {return selector==='input,textarea,select' ? [select,field] :
      [select,field,...options.filter(option=>option.role)]},
    createTreeWalker() {return {nextNode:()=>null}}, createRange() {return {}},
    getElementById() {return null}, elementFromPoint() {return this.covered ? {} : select},
  };
  global.location = {href:'http://fixture.test/select'};
  return {select,options,field,group,events,document,form};
};
