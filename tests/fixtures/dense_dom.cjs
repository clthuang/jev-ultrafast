// Scalable DOM adapter: production snapshot.js runs unchanged against these objects, as with select_dom.cjs.
// Config: n grid controls inside the viewport (kind 'button' with a text label, or 'input' with an aria-label);
// scope 'shared' (one <form> whose text is scopeChars long) or 'row' (rowSize controls per <li>, each with its own
// text); labelChars of padding per label ('€' when multibyte); select: one single dropdown with duplicate labels;
// multiple: one multi-select (evidence only); field: one text field; offscreen: one form field below the viewport.
// counters.scopeReads counts every innerText read of a scope, independently of snapshot.js.
module.exports = function createDOM(config = {}) {
  const n = config.n ?? 3, kind = config.kind ?? 'button', rowSize = config.rowSize ?? 10;
  const scopeChars = config.scopeChars ?? 200, labelChars = config.labelChars ?? 0;
  const pad = labelChars ? ' ' + (config.multibyte ? '€' : 'x').repeat(labelChars) : '';
  global.window = global;
  global.performance = {timeOrigin: 1759560000000.125};
  global.crypto = require('node:crypto').webcrypto;
  global.innerWidth = 1120; global.innerHeight = 780; global.scrollX = 0; global.scrollY = 0;
  global.NodeFilter = {SHOW_TEXT: 4};
  global.Event = class {constructor(type) {this.type = type}};
  global.requestAnimationFrame = callback => setTimeout(callback, 0);
  global.location = {href: 'http://fixture.test/dense'};
  const counters = {scopeReads: 0}, events = [];
  // The simple selectors snapshot.js uses, matched against one element.
  const simple = (e, selector) => {
    if (selector === '[aria-hidden="true"]') return e.getAttribute('aria-hidden') === 'true';
    if (selector === '[aria-disabled="true"]') return e.getAttribute('aria-disabled') === 'true';
    if (selector === '[inert]') return !!e.inert;
    if (selector === 'optgroup[disabled]') return e.tagName === 'OPTGROUP' && !!e.disabled;
    const role = /^\[role="(.+)"\]$/.exec(selector);
    if (role) return e.getAttribute('role') === role[1];
    return e.tagName === selector.toUpperCase();
  };
  class Element {
    constructor(tagName, props = {}) {
      Object.assign(this, {tagName, localName: tagName.toLowerCase(), attrs: {}, parentElement: null,
        isConnected: true, hidden: false, inert: false, disabled: false, readOnly: false, isContentEditable: false,
        rect: {x: 0, y: 0, width: 0, height: 0}, childNodes: [], labels: []}, props);
    }
    getAttribute(name) { return this.attrs[name] ?? null; }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    closest(selector) {
      const list = selector.split(',');
      for (let e = this; e; e = e.parentElement) if (list.some(s => simple(e, s))) return e;
      return null;
    }
    matches(selector) { return selector === ':disabled' && !!this.disabled; }
    checkVisibility() {
      for (let e = this; e; e = e.parentElement) if (e.hidden || !e.isConnected) return false;
      return true;
    }
    getBoundingClientRect() { return {...this.rect, top: this.rect.y, left: this.rect.x,
      right: this.rect.x + this.rect.width, bottom: this.rect.y + this.rect.height}; }
    contains(node) {
      for (let e = node; e; e = e.parentElement) if (e === this) return true;
      return false;
    }
    querySelector() { return null; }
    dispatchEvent(event) { events.push({event: event.type, key: this.key, index: this.selectedIndex}); return true; }
  }
  const scope = (tagName, text, parentElement = null) => {
    const e = new Element(tagName, {parentElement, text});
    Object.defineProperty(e, 'innerText', {get() { counters.scopeReads++; return this.text; }});
    return e;
  };
  const textNode = (parentElement, textContent) => ({nodeType: 3, textContent, parentElement,
    get rect() { return parentElement.rect; }});
  const base = 'Shared context: prices, dates and conditions for every control on this page. ';
  const body = new Element('BODY');
  const form = scope('FORM', base.repeat(Math.ceil(scopeChars / base.length)).slice(0, scopeChars), body);
  const context = new Element('P', {parentElement: form, rect: {x: 0, y: 0, width: 1120, height: 20}});
  const texts = [textNode(context, form.text)], candidates = [], controls = [], rows = [];
  let top = 24;
  const place = height => { const rect = {x: 10, y: top, width: 200, height}; top += height + 4; return rect; };
  let select = null, options = [], multiple = null, field = null, offscreen = null;
  if (config.select) {
    select = new Element('SELECT', {key: 'category', parentElement: form, multiple: false, rect: place(30)});
    select.attrs['aria-label'] = 'Category';
    options = [['placeholder', '', 'Choose', true], ['first', 'same', 'Same'], ['second', 'same', 'Same'],
      ['other', 'other', 'Other']].map(([key, value, label, selected]) =>
      new Element('OPTION', {key, value, label, selected: !!selected, parentElement: select}));
    Object.defineProperties(select, {
      options: {get() { return options.filter(o => o.isConnected && o.parentElement === select); }},
      selectedOptions: {get() { return this.options.filter(o => o.selected); }},
      selectedIndex: {get() { return this.options.findIndex(o => o.selected); },
        set(index) { this.options.forEach((o, i) => { o.selected = i === index; }); }},
      value: {get() { return this.selectedOptions[0]?.value ?? ''; }},
    });
    candidates.push(select);
  }
  if (config.multiple) {
    multiple = new Element('SELECT', {key: 'interests', parentElement: form, multiple: true, rect: place(60)});
    multiple.attrs['aria-label'] = 'Interests';
    const choices = [['one', 'First interest', true], ['two', 'Second interest', true], ['three', 'Third', false]]
      .map(([value, label, selected]) => new Element('OPTION', {value, label, selected, parentElement: multiple}));
    Object.defineProperties(multiple, {
      options: {get() { return choices; }},
      selectedOptions: {get() { return choices.filter(o => o.selected); }},
      selectedIndex: {get() { return choices.findIndex(o => o.selected); }},
      value: {get() { return this.selectedOptions[0]?.value ?? ''; }},
    });
    candidates.push(multiple);
  }
  if (config.field) {
    field = new Element('INPUT', {key: 'query', type: 'text', value: 'old', checked: false, parentElement: form,
      rect: place(30)});
    field.attrs['aria-label'] = 'Query';
    candidates.push(field);
  }
  // A fixed grid below the named controls keeps every control's center inside the 1120x780 viewport.
  const cols = Math.max(1, Math.ceil(Math.sqrt(n * innerWidth / (innerHeight - top)))), lines = Math.ceil(n / cols);
  const width = innerWidth / cols, height = (innerHeight - top) / Math.max(1, lines);
  for (let i = 0; i < n; i++) {
    let parent = form;
    if (config.scope === 'row') {
      const index = Math.floor(i / rowSize);
      if (!rows[index]) rows[index] = scope('LI', `Row ${index + 1}: fare rules and seat map for this row.`, form);
      parent = rows[index];
    }
    const rect = {x: (i % cols) * width, y: top + Math.floor(i / cols) * height,
      width: Math.max(1, width - 1), height: Math.max(1, height - 1)};
    const label = 'Control ' + (i + 1) + pad;
    let control;
    if (kind === 'input') {
      control = new Element('INPUT', {key: 'c' + i, type: 'text', value: '', checked: false, parentElement: parent,
        rect});
      control.attrs['aria-label'] = label;
    } else {
      control = new Element('BUTTON', {key: 'c' + i, type: 'submit', value: '', parentElement: parent, rect});
      control.childNodes = [textNode(control, label)];
      texts.push(control.childNodes[0]);
    }
    controls.push(control);
    candidates.push(control);
  }
  if (config.offscreen) {
    offscreen = new Element('INPUT', {key: 'offscreen', type: 'text', value: 'kept', checked: false,
      parentElement: form, rect: {x: 10, y: 3000, width: 200, height: 30}});
    offscreen.attrs['aria-label'] = 'Offscreen';
    candidates.push(offscreen);
  }
  const cover = new Element('DIV', {parentElement: body});
  const document = global.document = {
    body, title: 'Dense fixture', documentElement: {scrollHeight: 780}, covered: false,
    querySelectorAll(selector) {
      const live = candidates.filter(e => e.isConnected);
      return selector === 'input,textarea,select' ? live.filter(e => ['INPUT', 'SELECT'].includes(e.tagName)) : live;
    },
    createTreeWalker() {
      let i = 0;
      return {nextNode: () => texts[i++] || null};
    },
    createRange() {
      return {selectNodeContents(node) { this.node = node; }, getBoundingClientRect() {
        const r = this.node.rect;
        return {width: r.width, height: r.height, top: r.y, left: r.x, right: r.x + r.width, bottom: r.y + r.height};
      }};
    },
    getElementById() { return null; },
    elementFromPoint(x, y) {
      if (this.covered) return cover;
      const hit = [...candidates].reverse().find(e => e.isConnected && e.checkVisibility() &&
        x >= e.rect.x && x < e.rect.x + e.rect.width && y >= e.rect.y && y < e.rect.y + e.rect.height);
      return hit || body;
    },
  };
  return {Element, form, rows, controls, select, options, multiple, field, offscreen, counters, events, document,
    texts, candidates};
};
