import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createContext, runInContext } from 'node:vm';
import ts from 'typescript';

class Element extends EventTarget {
  hidden = false; open = false; tabIndex = 0; isConnected = true; blocked = false; dataset: Record<string,string> = {};
  attributes = new Map<string,string>(); values = new Map<string,string>(); captures = new Set<number>(); classes = new Set<string>();
  contained = new Set<Element>();
  style = { setProperty: (key:string,value:string) => this.values.set(key,value) };
  classList = { add: (key:string) => this.classes.add(key), remove: (key:string) => this.classes.delete(key) };
  bounds = { left:0,top:180,width:1400,right:1400,bottom:1000,height:820 };
  queuedClose = false; closeEvents: (()=>void)[] = [];
  onFocus = () => undefined;
  setAttribute(key:string,value:string) { this.attributes.set(key,value); }
  getBoundingClientRect() { return this.bounds; }
  focus() { this.onFocus(); }
  closest(_selector:string): Element|null { return this.blocked ? this : null; }
  contains(other: Element|null):boolean { return other === this || other !== null && this.contained.has(other); }
  setPointerCapture(id:number) { this.captures.add(id); }
  hasPointerCapture(id:number) { return this.captures.has(id); }
  releasePointerCapture(id:number) { this.captures.delete(id); }
  showModal() { this.open=true; }
  close() { if(this.open) { this.open=false; const dispatch=()=>this.dispatchEvent(new Event('close')); if(this.queuedClose)this.closeEvents.push(dispatch);else dispatch(); } }
  flushCloseEvents() { for(const dispatch of this.closeEvents.splice(0))dispatch(); }
  fire(type:string,properties:Record<string,unknown>={}) { const event=new Event(type,{cancelable:true}); for(const[key,value]of Object.entries(properties))Object.defineProperty(event,key,{value}); this.dispatchEvent(event); return event; }
  pressEscape() { const event=this.fire('cancel'); if(!event.defaultPrevented)this.close(); }
}
interface Helper {
  activateResults(options?:{focus?:boolean}):void;
  activateCatalogue(options?:{focus?:boolean}):void;
  openDetail(opener?:Element|null):void;
  closeDetail(options?:{restoreFocus?:boolean}):void;
  layoutWidth(value:unknown,available:number):number;
}
const compiled=ts.transpileModule(readFileSync('src/archsearch/frontend/workspace.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
function setup(options:{saved?:string;small?:boolean;storageFails?:boolean}={}) {
  const ids=['workspace','workspace-divider','workspace-sidebar','workspace-tab-results','workspace-tab-catalogue','workspace-results-view','workspace-catalogue-view','detail-dialog','detail-panel','close-detail','workspace-examples','llm-settings'];
  const nodes=new Map(ids.map(id=>[id,new Element()]));
  const document=new EventTarget() as EventTarget&{activeElement:Element|null;getElementById(id:string):Element|undefined;querySelector(selector:string):Element};
  document.activeElement=null; document.getElementById=id=>nodes.get(id); document.querySelector=()=>new Element();
  for(const node of nodes.values())node.onFocus=()=>{document.activeElement=node;};
  const window=new EventTarget() as EventTarget&{innerHeight:number;matchMedia(query:string):{matches:boolean}};
  window.innerHeight=1000; window.matchMedia=()=>({matches:options.small??false});
  const writes:{key:string;value:string}[]=[]; let changes=0,closed=0;
  window.addEventListener('archsearch:workspacechange',()=>changes++);window.addEventListener('archsearch:detailclose',()=>closed++);
  const context=createContext({window,document,HTMLElement:Element,Event,localStorage:{getItem:()=>{if(options.storageFails)throw new Error('blocked');return options.saved??null;},setItem:(key:string,value:string)=>{if(options.storageFails)throw new Error('blocked');writes.push({key,value});}}});
  const helper=runInContext(compiled+'\nArchSearchWorkspace;',context) as Helper;
  return{helper,document,window,writes,node:(id:string)=>nodes.get(id)!,changes:()=>changes,closed:()=>closed};
}

test('the workspace opens results and exposes one keyboard tab stop without changing search state',()=>{
  const h=setup();assert.equal(h.node('workspace-results-view').hidden,false);assert.equal(h.node('workspace-catalogue-view').hidden,true);
  assert.equal(h.node('workspace-tab-results').tabIndex,0);assert.equal(h.node('workspace-tab-catalogue').tabIndex,-1);assert.equal(h.writes.length,0);
});
test('tabs support arrows and Home/End, with explicit focus and resize notifications',()=>{
  const h=setup();const before=h.changes();
  assert.equal(h.node('workspace-tab-results').fire('keydown',{key:'ArrowRight'}).defaultPrevented,true);
  assert.equal(h.node('workspace-catalogue-view').hidden,false);assert.equal(h.document.activeElement,h.node('workspace-tab-catalogue'));
  h.node('workspace-tab-catalogue').fire('keydown',{key:'Home'});assert.equal(h.document.activeElement,h.node('workspace-tab-results'));
  h.node('workspace-tab-results').fire('keydown',{key:'End'});assert.equal(h.document.activeElement,h.node('workspace-tab-catalogue'));assert.ok(h.changes()>before);
});
test('programmatic result activation can retain the current query focus',()=>{
  const h=setup();h.helper.activateCatalogue();const input=new Element();h.document.activeElement=input;
  h.helper.activateResults({focus:false});assert.equal(h.document.activeElement,input);assert.equal(h.node('workspace-results-view').hidden,false);
});
test('programmatic activation restores focus from a panel it hides while preserving an unrelated map focus',()=>{
  const h=setup();h.helper.activateCatalogue();const country=new Element();h.node('workspace-catalogue-view').contained.add(country);h.document.activeElement=country;
  h.helper.activateResults({focus:false});
  assert.equal(h.node('workspace-catalogue-view').hidden,true);assert.equal(h.document.activeElement,h.node('workspace-tab-results'));
  const resultButton=new Element();h.node('workspace-results-view').contained.add(resultButton);h.document.activeElement=resultButton;
  h.helper.activateCatalogue({focus:false});assert.equal(h.document.activeElement,h.node('workspace-tab-catalogue'));
  const map=new Element();h.document.activeElement=map;h.helper.activateResults({focus:false});assert.equal(h.document.activeElement,map);
});
test('keyboard resizing clamps dimensions and stores only an explicit layout width',()=>{
  const h=setup();const divider=h.node('workspace-divider');divider.fire('keydown',{key:'End'});assert.equal(divider.attributes.get('aria-valuenow'),'580');
  divider.fire('keydown',{key:'ArrowRight'});assert.equal(divider.attributes.get('aria-valuenow'),'580');
  divider.fire('keydown',{key:'Home'});assert.equal(divider.attributes.get('aria-valuenow'),'280');divider.fire('keydown',{key:'ArrowRight'});assert.equal(divider.attributes.get('aria-valuenow'),'296');
  assert.deepEqual(JSON.parse(h.writes.at(-1)!.value),{sidebar_width:296});assert.equal(h.writes.at(-1)!.key,'archsearch.workspace.layout.v1');
});
test('pointer resizing uses capture and keeps space for both maps',()=>{
  const h=setup();const divider=h.node('workspace-divider');
  divider.fire('pointerdown',{button:0,isPrimary:true,pointerId:7});assert.equal(divider.hasPointerCapture(7),true);
  divider.fire('pointermove',{pointerId:7,clientX:500});assert.equal(divider.attributes.get('aria-valuenow'),'500');
  divider.fire('pointerup',{pointerId:7});assert.equal(divider.hasPointerCapture(7),false);assert.deepEqual(JSON.parse(h.writes.at(-1)!.value),{sidebar_width:500});
  assert.equal(h.helper.layoutWidth(580,1000),468);assert.equal(h.helper.layoutWidth(Infinity,1400),350);assert.equal(h.helper.layoutWidth(-10,1400),280);
});
test('narrow screens ignore divider dragging and keyboard resizing',()=>{
  const h=setup({small:true});const divider=h.node('workspace-divider');divider.fire('pointerdown',{button:0,isPrimary:true,pointerId:7});divider.fire('pointermove',{pointerId:7,clientX:500});divider.fire('keydown',{key:'End'});
  assert.equal(h.writes.length,0);assert.equal(divider.attributes.get('aria-valuenow'),'350');
});
test('restored preferences ignore arbitrary properties and malformed or blocked storage',()=>{
  const h=setup({saved:'{"sidebar_width":470,"query":"private","api_key":"secret"}'});h.node('workspace-divider').fire('keydown',{key:'ArrowLeft'});
  assert.deepEqual(JSON.parse(h.writes.at(-1)!.value),{sidebar_width:454});
  assert.doesNotThrow(()=>setup({saved:'broken json'}));assert.doesNotThrow(()=>setup({storageFails:true}).node('workspace-divider').fire('keydown',{key:'End'}));
});
test('native detail dialogs focus their close action and restore a valid opener',()=>{
  const h=setup();const opener=new Element();opener.onFocus=()=>{h.document.activeElement=opener;};
  h.helper.openDetail(opener);assert.equal(h.node('detail-dialog').open,true);assert.equal(h.node('detail-panel').hidden,false);assert.equal(h.document.activeElement,h.node('close-detail'));
  h.node('close-detail').fire('click');assert.equal(h.node('detail-dialog').open,false);assert.equal(h.document.activeElement,opener);assert.equal(h.closed(),1);assert.equal(h.node('detail-panel').hidden,true);
});
test('native Escape closes the dialog and removed or hidden openers fall back to the active tab',()=>{
  const h=setup();const opener=new Element();opener.isConnected=false;h.helper.activateCatalogue();h.helper.openDetail(opener);h.node('detail-dialog').pressEscape();assert.equal(h.document.activeElement,h.node('workspace-tab-catalogue'));
  opener.isConnected=true;opener.blocked=true;h.helper.openDetail(opener);h.helper.closeDetail();assert.equal(h.document.activeElement,h.node('workspace-tab-catalogue'));
});
test('programmatic closing can skip restoring a previous opener',()=>{
  const h=setup();h.helper.openDetail(new Element());const current=new Element();h.document.activeElement=current;h.helper.closeDetail({restoreFocus:false});assert.equal(h.document.activeElement,current);
});
test('an asynchronously queued old close cannot hide a reopened detail or replace its opener',()=>{
  const h=setup();const dialog=h.node('detail-dialog');dialog.queuedClose=true;
  const first=new Element(),second=new Element();first.onFocus=()=>{h.document.activeElement=first;};second.onFocus=()=>{h.document.activeElement=second;};
  h.helper.openDetail(first);h.helper.closeDetail({restoreFocus:false});h.helper.openDetail(second);
  assert.equal(dialog.open,true);assert.equal(h.node('detail-panel').hidden,false);
  dialog.flushCloseEvents();
  assert.equal(dialog.open,true);assert.equal(h.node('detail-panel').hidden,false);assert.equal(h.closed(),0);assert.equal(h.document.activeElement,h.node('close-detail'));
  h.helper.closeDetail();dialog.flushCloseEvents();
  assert.equal(h.node('detail-panel').hidden,true);assert.equal(h.document.activeElement,second);assert.equal(h.closed(),1);
});
test('only a real backdrop click closes the native dialog',()=>{
  const h=setup();const dialog=h.node('detail-dialog');dialog.bounds={left:100,top:100,right:700,bottom:700,width:600,height:600};h.helper.openDetail();
  dialog.fire('click',{clientX:200,clientY:200});assert.equal(dialog.open,true);dialog.fire('click',{clientX:20,clientY:20});assert.equal(dialog.open,false);
});
test('popover menus close each other and Escape dismisses them when no modal is active',()=>{
  const h=setup();h.node('workspace-examples').open=true;h.node('llm-settings').open=true;h.node('llm-settings').fire('toggle');assert.equal(h.node('workspace-examples').open,false);
  const escape=new Event('keydown');Object.defineProperty(escape,'key',{value:'Escape'});h.document.dispatchEvent(escape);assert.equal(h.node('llm-settings').open,false);
});
