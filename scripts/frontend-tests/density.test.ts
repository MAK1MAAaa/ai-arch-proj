import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createContext,runInContext} from 'node:vm';
import ts from 'typescript';

interface Placement {id:string;title:string;coordinate:[number,number];representative:boolean;tooltip?():Element}
interface Pixel {x:number;y:number}
interface Item {value:Placement;coordinate:[number,number];pixel:Pixel;copy:number}
interface Group {key:string;items:Item[];pixel:Pixel;focusPixel:Pixel;copy:number}
interface Viewport {origin:Pixel;width:number;height:number;worldWidth:number;cellSize?:number;selectedId?:string|null}
interface Controller {layer:Layer;setData(values:Placement[]):void;select(id:string|null):void;refresh():void;destroy():void;stats():{logicalPoints:number;visiblePoints:number;clusters:number;symbols:number}}
interface Helpers {valid(value:unknown):boolean;plan(values:Placement[],project:(coordinate:[number,number])=>Pixel,viewport:Viewport):Group[];members(group:Group):Placement[];create(options:{map:MapView;pane:string;renderer:object;cellSize?:number;onSelect(id:string,opener:Element):void}):Controller}
class Element extends EventTarget {
  textContent='';className='';tabIndex=0;disabled=false;type='';isConnected=true;
  style:Record<string,string>={};dataset:Record<string,string>={};attributes=new Map<string,string>();children:Element[]=[];
  onFocus?:()=>void;
  scrolls=0;onScroll?:()=>void;bounds={left:0,top:0,right:600,bottom:400,width:600,height:400};
  append(...children:Element[]){this.children.push(...children);}replaceChildren(...children:Element[]){this.children=children;}
  setAttribute(key:string,value:string){this.attributes.set(key,value);}contains(value:Element|null):boolean{return value===this||this.children.some(child=>child.contains(value));}
  focus(){this.onFocus?.();}getBoundingClientRect(){return this.bounds;}scrollIntoView(){this.scrolls++;this.onScroll?.();}
  fire(type:string,key?:string){const event=new Event(type,{cancelable:true});if(key)Object.defineProperty(event,'key',{value:key});this.dispatchEvent(event);return event;}
  set innerHTML(_value:string){throw new Error('Unsafe HTML');}
}
class Events {
  listeners=new Map<string,(()=>void)[]>();on(names:string,callback:()=>void){for(const name of names.split(' '))this.listeners.set(name,[...(this.listeners.get(name)??[]),callback]);return this;}
  off(names:string,callback:()=>void){for(const name of names.split(' '))this.listeners.set(name,(this.listeners.get(name)??[]).filter(item=>item!==callback));return this;}
  fire(name:string){for(const callback of [...(this.listeners.get(name)??[])])callback();return this;}
}
class Layer extends Events {
  layers=new Set<Layer>();parent:{layers:Set<Layer>}|null=null;element=new Element();options:Record<string,unknown>={};location={lat:0,lng:0};tooltip:(()=>Element)|null=null;
  addTo(parent:{layers:Set<Layer>}){this.parent=parent;parent.layers.add(this);this.fire('add');return this;}
  clearLayers(){for(const child of this.layers)child.element.isConnected=false;this.layers.clear();return this;}
  removeLayer(child:Layer){child.element.isConnected=false;this.layers.delete(child);return this;}
  remove(){this.parent?.layers.delete(this);this.fire('remove');return this;}
  getElement(){return this.element;}setRadius(radius:number){this.options.radius=radius;return this;}setStyle(value:object){Object.assign(this.options,value);return this;}
  bindTooltip(value:()=>Element){this.tooltip=value;return this;}bringToFront(){return this;}
  setLatLng(value:[number,number]|{lat:number;lng:number}){this.location=Array.isArray(value)?{lat:value[0],lng:value[1]}:{...value};return this;}
}
class Popup extends Layer {
  content=new Element();openCount=0;setContent(value:Element){this.content=value;this.element.children=[value];return this;}
  openOn(map:MapView){this.openCount++;map.popup=this;this.parent=map;return this;}
  override remove(){if(this.parent instanceof MapView)this.parent.popup=null;return super.remove();}
}
class MapView extends Events {
  layers=new Set<Layer>();panes=new Map<string,Element>();container=new Element();center={lat:0,lng:0};zoom=1;width=600;height=400;popup:Popup|null=null;cameraChanges=0;
  paneParents=new Map<string,Element|undefined>();paneOffset={x:0,y:0};
  getCenter(){return this.center;}getZoom(){return this.zoom;}getSize(){return{x:this.width,y:this.height};}getContainer(){return this.container;}
  getPane(name:string){return this.panes.get(name);}createPane(name:string,parent?:Element){const pane=new Element();this.panes.set(name,pane);this.paneParents.set(name,parent);return pane;}
  layerPointToContainerPoint(point:[number,number]){return{x:point[0]+this.paneOffset.x,y:point[1]+this.paneOffset.y};}
  hasLayer(layer:Layer){return this.layers.has(layer);}
  removeLayer(layer:Layer){this.layers.delete(layer);layer.fire('remove');return this;}
  project(value:[number,number]|{lat:number;lng:number},zoom=this.zoom){const v=Array.isArray(value)?{lat:value[0],lng:value[1]}:value;const scale=256*2**zoom;return{x:(v.lng+180)/360*scale,y:(90-v.lat)/180*scale};}
  unproject(value:[number,number],zoom=this.zoom){const scale=256*2**zoom;return{lng:value[0]/scale*360-180,lat:90-value[1]/scale*180};}
  stop(){}setView(value:{lat:number;lng:number},zoom:number){this.center={...value};this.zoom=zoom;this.cameraChanges++;this.fire('zoomend').fire('moveend');return this;}
}
const script=ts.transpileModule(readFileSync('src/archsearch/frontend/density.ts','utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;
function harness(cellSize=48){
  const doc={activeElement:null as Element|null,querySelector:()=>null,createElement:()=>{const element=new Element();element.onFocus=()=>{doc.activeElement=element;};return element;}};
  const viewport={innerWidth:600,innerHeight:400};
  const frames:(()=>void)[]=[];const map=new MapView();map.container.onFocus=()=>{doc.activeElement=map.container;};
  const popups:Popup[]=[],markers:Layer[]=[],circles:Layer[]=[];
  const helpers=runInContext(script+'\nArchSearchDensity;',createContext({Event,window:viewport,document:doc,requestAnimationFrame:(fn:()=>void)=>frames.push(fn),
    L:{layerGroup:()=>new Layer(),circleMarker:(coordinate:[number,number],options:Record<string,unknown>)=>{const circle=new Layer().setLatLng(coordinate);circle.options={...options};circles.push(circle);return circle;},
      marker:(coordinate:{lat:number;lng:number},options:Record<string,unknown>)=>{const marker=new Layer().setLatLng(coordinate);marker.options={...options};marker.element.onFocus=()=>{doc.activeElement=marker.element;};markers.push(marker);return marker;},
      divIcon:(options:object)=>options,popup:()=>{const popup=new Popup();popups.push(popup);return popup;}}})) as Helpers;
  const selected:{id:string;opener:Element}[]=[];const controller=helpers.create({map,pane:'source-points',renderer:{source:true},cellSize,onSelect:(id,opener)=>selected.push({id,opener})});controller.layer.addTo(map);
  return{helpers,controller,map,doc,viewport,frames,popups,markers,circles,selected,flush:()=>{const callbacks=frames.splice(0);callbacks.forEach(fn=>fn());}};
}
const value=(id:string,x=0,y=0):Placement=>({id,title:id,coordinate:[x,y],representative:false});
const viewport:Viewport={origin:{x:0,y:0},width:512,height:512,worldWidth:512};
const projection=([x,y]:[number,number]):Pixel=>({x:(x+180)/360*512,y:(90-y)/180*512});
const nodes=(element:Element):Element[]=>[element,...element.children.flatMap(nodes)];
const findAction=(popup:Popup,action:string)=>{const node=nodes(popup.content).find(item=>item.dataset.action===action);assert.ok(node);return node;};
const memberButtons=(popup:Popup)=>nodes(popup.content).filter(item=>item.dataset.siteId);

test('logical placements deduplicate within an identity without conflating different records or world copies',()=>{
  const h=harness(),values=[value('same',2,3),value('same',2,3),value('other',2,3),value('same',3,3)];
  const groups=h.helpers.plan(values,projection,{...viewport,origin:{x:-512,y:0},width:1536});
  const middle=groups.filter(group=>group.items.some(item=>item.copy===0));
  assert.equal(middle.reduce((sum,group)=>sum+group.items.length,0),3);
  assert.equal(groups.reduce((sum,group)=>sum+group.items.length,0),9);
  assert.ok(groups.every(group=>new Set(group.items.map(item=>JSON.stringify([item.value.id,...item.value.coordinate]))).size===group.items.length));
  assert.deepEqual(JSON.parse(JSON.stringify(values[0].coordinate)),[2,3]);
});
test('dateline neighbors share their physical screen cell without inflating their logical membership',()=>{
  const h=harness();const groups=h.helpers.plan([value('east',179.9),value('west',-179.9)],projection,{...viewport,origin:{x:460,y:0},width:100});
  assert.equal(groups.length,1);assert.equal(groups[0].items.length,2);assert.equal(h.helpers.members(groups[0]).length,2);
  assert.deepEqual(JSON.parse(JSON.stringify(groups[0].items.map(item=>item.coordinate))),[[179.9,0],[180.1,0]]);
});
test('adjacent dense cell anchors cannot overlap and zoom focus keeps the real member center',()=>{
  const h=harness();const project=([x,y]:[number,number])=>({x,y});
  const groups=h.helpers.plan([value('a',47.8,30),value('b',47.9,30),value('c',48.1,30),value('d',48.2,30)],project,{...viewport,width:120,height:100,worldWidth:360});
  assert.equal(groups.length,2);assert.equal(Math.abs(groups[0].pixel.x-groups[1].pixel.x),48);
  assert.ok(groups[0].focusPixel.x>47&&groups[0].focusPixel.x<48);assert.equal(groups[0].pixel.x,24);
});
test('invalid and polar locations are omitted; genuine zero and selected coordinates retain their source meaning',()=>{
  const h=harness();for(const coordinate of [null,[null,null],[181,0],[0,86],[NaN,0]])assert.equal(h.helpers.valid(coordinate),false);
  const groups=h.helpers.plan([value('chosen',0),value('near',0),value('third',1),{...value('bad'),coordinate:null as unknown as [number,number]}],projection,{...viewport,selectedId:'chosen'});
  assert.equal(groups.reduce((sum,group)=>sum+group.items.length,0),3);assert.ok(groups.every(group=>group.items.length===1));
  const selected=groups.find(group=>group.items[0].value.id==='chosen')!;assert.deepEqual(JSON.parse(JSON.stringify(selected.items[0].coordinate)),[0,0]);
});
test('world-anchored grouping is stable under small pans while culling complete distant cells',()=>{
  const h=harness(),values=[value('one',2,3),value('two',3,3),value('far',150,70)];
  const a=h.helpers.plan(values,projection,viewport),b=h.helpers.plan(values,projection,{...viewport,origin:{x:5,y:0}});
  const key=(groups:Group[])=>groups.filter(group=>group.items.length>1).map(group=>group.key+':'+group.items.map(item=>item.value.id).join(','));
  assert.deepEqual(key(a),key(b));assert.equal(h.helpers.plan(values,projection,{...viewport,origin:{x:0,y:400},height:80}).length,0);
});
test('maximum zoom keeps all coincident records reachable through stable popup pagination and real selection',()=>{
  const h=harness();h.map.zoom=9;h.controller.setData(Array.from({length:25},(_,index)=>value('site:'+String(index).padStart(2,'0'))));
  assert.equal(h.controller.stats().clusters,1);h.markers[0].fire('click');const popup=h.popups[0];
  assert.equal(memberButtons(popup).length,10);assert.equal(findAction(popup,'zoom').disabled,true);
  assert.equal(h.doc.activeElement,popup.content.children[0]);
  findAction(popup,'next').fire('click');findAction(popup,'next').fire('click');
  assert.equal(memberButtons(popup).length,5);assert.equal(findAction(popup,'next').disabled,true);
  memberButtons(popup).at(-1)!.fire('click');assert.equal(h.selected[0].id,'site:24');assert.equal(h.selected[0].opener,memberButtons(popup).at(-1));
  assert.equal(h.map.cameraChanges,0);assert.match(popup.content.children[0].textContent,/25 个定位点 \/ 25 条资料/u);
});
test('pan, zoom and resize coalesce point redraws without rebuilding or taking focus from an open member list',()=>{
  const h=harness();h.controller.setData([value('one'),value('two')]);h.markers[0].fire('click');const popup=h.popups[0];
  const button=memberButtons(popup)[0];button.focus();const content=popup.content;
  h.map.setView({lat:2,lng:3},3);h.map.width=390;h.map.height=380;h.map.fire('resize');
  assert.equal(h.frames.length,1);h.flush();
  assert.equal(h.map.popup,popup);assert.equal(popup.content,content);assert.equal(h.doc.activeElement,button);assert.equal(h.popups.length,1);
  findAction(popup,'zoom').fire('click');h.flush();assert.equal(h.map.getZoom(),5);
});
test('Escape from popup members returns focus to a current map control after redraw removes its source marker',()=>{
  const h=harness();h.controller.setData([value('one'),value('two')]);h.markers[0].fire('click');const popup=h.popups[0];
  h.map.setView({lat:80,lng:100},7);h.flush();const button=memberButtons(popup)[0];button.focus();
  const escape=popup.element.fire('keydown','Escape');assert.equal(escape.defaultPrevented,true);assert.equal(h.map.popup,null);assert.equal(h.doc.activeElement,h.map.container);
});
test('selection retains a member popup and applies accurate circle highlighting without changing cameras',()=>{
  const h=harness();h.controller.setData([value('one'),value('two')]);h.markers[0].fire('click');const popup=h.popups[0],button=memberButtons(popup)[0];button.focus();
  h.controller.select('one');assert.equal(h.map.popup,popup);assert.equal(h.doc.activeElement,button);assert.equal(button.attributes.get('aria-pressed'),'true');
  assert.ok(h.circles.some(circle=>circle.options.radius===5));assert.equal(h.map.cameraChanges,0);
  h.controller.layer.remove();assert.equal(h.map.popup,null);assert.equal(h.map.container.dataset.densitySymbols,'0');
});
test('destroying a density layer detaches only its own redraw listeners',()=>{
  const h=harness();h.controller.setData([value('one'),value('two')]);h.controller.destroy();h.map.fire('moveend').fire('resize');assert.equal(h.frames.length,0);
  assert.equal(h.map.layers.size,0);assert.equal(h.controller.layer.listeners.get('add')?.length,0);assert.equal(h.map.container.dataset.densitySymbols,'0');
});

test('hiding and readding an unchanged viewport restores symbols and notifies label layout on cache hits',()=>{
  const h=harness();h.controller.setData([value('one'),value('two')]);let changes=0;h.map.on('archsearch:markerschange',()=>changes++);
  const symbols=h.map.container.dataset.densitySymbols;assert.equal(symbols,'1');
  h.controller.layer.remove();assert.equal(h.map.container.dataset.densitySymbols,'0');
  h.controller.layer.addTo(h.map);assert.equal(h.map.container.dataset.densitySymbols,symbols);assert.equal(h.map.container.dataset.densityClusters,'1');assert.equal(changes,2);
});

test('larger map-role cells reduce symbol density while retaining the same logical placements',()=>{
  const modern=harness(48),historical=harness(128),values=Array.from({length:40},(_,index)=>value('site:'+index,-50+index*2.5));
  modern.map.width=historical.map.width=256;
  modern.controller.setData(values);historical.controller.setData(values);
  assert.equal(modern.controller.stats().logicalPoints,40);assert.equal(historical.controller.stats().logicalPoints,40);
  assert.ok(historical.controller.stats().symbols<modern.controller.stats().symbols);
  assert.equal(historical.map.container.dataset.densityCellSize,'128');assert.equal(modern.map.cameraChanges+historical.map.cameraChanges,0);
});

test('opening from a partly visible canvas scrolls only the document and fits the member list into visible map space',()=>{
  const h=harness();h.map.container.bounds={left:0,top:330,right:600,bottom:730,width:600,height:400};
  h.map.container.onScroll=()=>{h.map.container.bounds={left:0,top:0,right:600,bottom:400,width:600,height:400};};
  h.controller.setData([value('one'),value('two')]);h.markers[0].fire('click');
  assert.equal(h.map.container.scrolls,1);assert.equal(h.map.cameraChanges,0);
  assert.equal(h.popups[0].content.style.maxHeight,'320px');assert.equal(h.doc.activeElement,h.popups[0].content.children[0]);
  h.map.center.lng=3;h.map.fire('moveend');h.flush();assert.equal(h.map.container.scrolls,1);
});

test('popup pane escapes the map-pane stacking context and tracks public pane offsets until destruction',()=>{
  const h=harness(),pane=h.map.panes.get('catalogue-density-popup');assert.ok(pane);
  assert.equal(h.map.paneParents.get('catalogue-density-popup'),h.map.container);assert.equal(pane.style.zIndex,'1100');assert.equal(pane.style.pointerEvents,'none');
  h.controller.setData([value('one'),value('two')]);h.markers[0].fire('click');const popup=h.popups[0],button=memberButtons(popup)[0];button.focus();
  h.map.paneOffset={x:37,y:-19};h.map.fire('move');assert.equal(pane.style.transform,'translate3d(37px, -19px, 0)');assert.equal(h.doc.activeElement,button);
  h.map.paneOffset={x:-8,y:22};h.map.fire('zoomanim');assert.equal(pane.style.transform,'translate3d(-8px, 22px, 0)');assert.equal(h.map.cameraChanges,0);
  h.controller.destroy();h.map.paneOffset={x:50,y:50};h.map.fire('move').fire('resize');assert.equal(pane.style.transform,'translate3d(-8px, 22px, 0)');
  assert.equal(h.map.listeners.get('move')?.length,0);assert.equal(h.map.popup,null);assert.equal(h.map.layers.size,0);
});
