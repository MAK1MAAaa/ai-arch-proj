import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createContext,runInContext} from 'node:vm';
import ts from 'typescript';

interface Placement {id:string;title:string;coordinate:[number,number];representative:boolean;tooltip?():Element}
interface Pixel {x:number;y:number}
interface Item {value:Placement;coordinate:[number,number];pixel:Pixel;copy:number}
interface Group {key:string;items:Item[];pixel:Pixel;focusPixel:Pixel;badge:boolean}
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
  const viewport=Object.assign(new EventTarget(),{innerWidth:600,innerHeight:400});
  const frames:(()=>void)[]=[];const map=new MapView();map.container.onFocus=()=>{doc.activeElement=map.container;};
  const popups:Popup[]=[],markers:Layer[]=[],circles:Layer[]=[];
  const helpers=runInContext(script+'\nArchSearchDensity;',createContext({Event,Element,window:viewport,document:doc,requestAnimationFrame:(fn:()=>void)=>frames.push(fn),
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
test('date line neighbors across a historical grid edge remain individually reachable in one badge', () => {
  const h = harness();
  const groups = h.helpers.plan([value('west',-179.9),value('east',179.9)], projection,
    {...viewport,origin:{x:460,y:0},width:100,cellSize:128});
  assert.equal(groups.length,1);
  assert.equal(groups[0].badge,true);
  assert.deepEqual(Array.from(h.helpers.members(groups[0]), member => member.id),['east','west']);
  assert.equal(groups[0].focusPixel.x,512);
  assert.equal(groups[0].pixel.x,512);
  assert.deepEqual(Array.from(groups[0].items, item => item.coordinate[0]).sort((a,b) => a-b),[179.9,180.1]);
});

test('nearby points at a grid corner form a stable group while distant points remain separate', () => {
  const h = harness(), project = ([x,y]:[number,number]) => ({x,y});
  const values = [value('a',47,47),value('b',49,47),value('c',47,49),value('d',49,49),value('separate',96,84)];
  const scope = {...viewport,width:192,height:128};
  for (const points of [values, [...values].reverse()]) {
    const groups = h.helpers.plan(points,project,scope);
    const badge = groups.find(group => group.badge)!;
    assert.equal(groups.length,2);
    assert.equal(badge.key,'0:0');
    assert.deepEqual(Array.from(h.helpers.members(badge), member => member.id), ['a','b','c','d']);
    assert.equal(groups.find(group => !group.badge)?.items[0].value.id,'separate');
  }
});

test('members visible at the viewport edge keep their cluster control reachable', () => {
  const h = harness(), project = ([x,y]:[number,number]) => ({x,y});
  const groups = h.helpers.plan([value('a',110,30),value('b',115,30)],project,
    {...viewport,origin:{x:100,y:0},width:390,cellSize:128});
  assert.equal(groups[0].pixel.x,112.5);
  assert.deepEqual(Array.from(h.helpers.members(groups[0]), member => member.id), ['a','b']);
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
  assert.equal(groups.reduce((sum,group)=>sum+group.items.length,0),3);
  const selected=groups.find(group=>group.items[0].value.id==='chosen')!;assert.equal(selected.badge,false);
  assert.deepEqual(JSON.parse(JSON.stringify(selected.items[0].coordinate)),[0,0]);
});

for (const cellSize of [48, 128]) {
  test(`selecting a point preserves a heavily populated cell at ${cellSize}px`, () => {
    const h = harness(), center = cellSize / 2, project = ([x, y]: [number, number]) => ({x,y});
    const values = [value('chosen', center + 20, center + 20), ...Array.from({length: 1200}, (_, index) => value(`site:${index}`, center, center))];
    const scope = {...viewport, width: 320, height: 300, cellSize};
    assert.equal(h.helpers.plan(values, project, scope).length, 1);
    const groups = h.helpers.plan(values, project, {...scope, selectedId: 'chosen'});
    const badge = groups.find(group => group.badge)!, chosen = groups.find(group => !group.badge)!;
    assert.equal(groups.length, 2);
    assert.equal(badge.items.length, 1200);
    assert.equal(h.helpers.members(badge).length, 1200);
    assert.ok(Math.abs(badge.pixel.x - chosen.pixel.x) >= 30 || Math.abs(badge.pixel.y - chosen.pixel.y) >= 30);
    assert.equal(chosen.pixel.x, center + 20);
    assert.equal(chosen.pixel.y, center + 20);
    assert.equal(badge.focusPixel.x, center);
    assert.equal(badge.focusPixel.y, center);
  });
}

test('coincident records keep a reachable badge after choosing one and preserve the original coordinate', () => {
  const h = harness();
  h.controller.setData([value('chosen'), value('other')]);
  h.controller.select('chosen');
  assert.equal(h.controller.stats().clusters, 1);
  assert.equal(h.controller.stats().symbols, 2);
  h.markers.at(-1)!.fire('click');
  const popup = h.popups.at(-1)!;
  assert.deepEqual(memberButtons(popup).map(button => button.dataset.siteId), ['other']);
  memberButtons(popup)[0].fire('click');
  assert.equal(h.selected.at(-1)?.id, 'other');
  findAction(popup, 'zoom').fire('click');
  assert.deepEqual(h.map.center, {lat: 0, lng: 0});
});

test('choosing a record with hundreds of source points keeps those points grouped around its representative point', () => {
  const h = harness(), project = ([x,y]:[number,number]) => ({x,y});
  const values = Array.from({length:750}, (_, index) => value('chosen', 25 + index / 1000, 23));
  values.push({...value('chosen',24,24),representative:true},value('other',23,23));
  const groups = h.helpers.plan(values,project,{...viewport,width:320,selectedId:'chosen'});
  assert.equal(groups.length,2);
  assert.equal(groups.find(group => group.badge)?.items.length,751);
  assert.equal(groups.find(group => !group.badge)?.items[0].value.representative,true);
});

test('selection does not pull offscreen copies into the visible map or count one point twice in a badge', () => {
  const h = harness(), projected = () => ({x:64,y:192});
  const points = [value('chosen'),value('other-a'),value('other-b')];
  const scope = {...viewport,origin:{x:220,y:0},cellSize:128,selectedId:'chosen'};
  for (const width of [192,390,640]) {
    const groups = h.helpers.plan(points,projected,{...scope,width});
    const badges = groups.filter(group => group.badge);
    const visible = badges.filter(group => group.pixel.x >= scope.origin.x && group.pixel.x <= scope.origin.x + width);
    assert.equal(visible.length,width === 192 ? 0 : 1);
    assert.ok(badges.every(group => new Set(group.items.map(item => item.value.id)).size === group.items.length));
  }
});

test('a visible badge accepts Enter and Space, and clipped badges stay outside the Tab order', () => {
  const h = harness();
  h.controller.setData([value('visible-a'),value('visible-b'),value('outside-a',-118),value('outside-b',-118)]);
  const visible = h.markers.find(marker => marker.getElement().tabIndex === 0)!;
  assert.ok(visible);
  assert.ok(h.markers.some(marker => marker.getElement().tabIndex === -1));
  visible.getElement().focus();
  assert.equal(visible.getElement().fire('keydown','Enter').defaultPrevented,true);
  assert.equal(h.popups.length,1);
  h.popups[0].element.fire('keydown','Escape');
  assert.equal(h.doc.activeElement,visible.getElement());
  assert.equal(visible.getElement().fire('keydown',' ').defaultPrevented,true);
  assert.equal(h.popups.length,2);
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

test('page and ancestor scroll only reposition an open popup, preserving its page and focus', () => {
  const h = harness();
  const scroll = (target: EventTarget | typeof h.doc = h.viewport) => {
    const event = new Event('scroll');
    Object.defineProperty(event, 'target', {value: target});
    h.viewport.dispatchEvent(event);
  };
  scroll(h.doc);
  assert.equal(h.frames.length, 0);
  h.controller.setData(Array.from({length: 12}, (_, index) => value('site:' + String(index).padStart(2, '0'))));
  h.markers[0].fire('click');
  const popup = h.popups[0], position = popup.location;
  findAction(popup, 'next').fire('click');
  const currentMember = memberButtons(popup)[0];
  assert.equal(currentMember.dataset.siteId, 'site:10');
  currentMember.focus();

  scroll(popup.content);
  assert.equal(h.frames.length, 0);
  const mapAncestor = new Element();
  mapAncestor.append(h.map.container);
  h.map.container.bounds = {left: 0, top: 150, right: 600, bottom: 550, width: 600, height: 400};
  scroll(mapAncestor);
  scroll(h.doc);
  assert.equal(h.frames.length, 1);
  h.flush();
  assert.notDeepEqual(popup.location, position);
  assert.equal(popup.content.style.maxHeight, '170px');
  assert.equal(h.doc.activeElement, currentMember);
  assert.equal(memberButtons(popup)[0], currentMember);
  assert.equal(h.map.container.scrolls, 0);
  assert.equal(h.map.cameraChanges, 0);
  assert.equal(h.popups.length, 1);
  assert.equal(h.markers.length, 1);

  scroll();
  const lastPosition = popup.location;
  popup.remove();
  h.flush();
  assert.deepEqual(popup.location, lastPosition);
  scroll();
  assert.equal(h.frames.length, 0);
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
