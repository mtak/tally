// Exercise the real leave guard with changed/reverted text and rejected submissions.
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const assert = require('node:assert/strict');
const code = readFileSync(require('node:path').join(__dirname, '../static/unsaved.js'), 'utf8');
for (const rejected of [false, true]) {
  const events = {}, windowEvents = {};
  const amount = {name:'amount', value:'100', type:'text'};
  const editor = {elements:[amount], dataset:{unsaved:String(rejected),leaveMessage:'Discard?'}};
  const preference = {value:'en'};
  let prompts=0, accept=false;
  const location = {pathname:'/valuations/1/',search:'',href:'http://localhost/valuations/1/'};
  runInNewContext(code, {URL, location, document:{
    querySelector:()=>editor, querySelectorAll:()=>[preference],
    addEventListener:(name,fn)=>events[name]=fn,
  }, window:{location,confirm:()=>{prompts++;return accept},addEventListener:(name,fn)=>windowEvents[name]=fn}});
  const submit = target => {const e={target,preventDefault(){this.defaultPrevented=true}};events.submit(e);return e};
  if (!rejected) {
    amount.value='123,45';
    preference.value='nl';
    assert.ok(submit({}).defaultPrevented);
    assert.equal(preference.value,'en');
    assert.equal(amount.value,'123,45');
    amount.value='100';
    const count=prompts;
    assert.equal(submit({}).defaultPrevented,undefined);
    assert.equal(prompts,count);
    windowEvents.pageshow();
  }
  amount.value='123.45';
  let prevented=false;
  windowEvents.beforeunload({preventDefault(){prevented=true}});
  assert.ok(prevented);
  const link = {href:'http://localhost/accounts/',hasAttribute:()=>false};
  const click={button:0,target:{closest:()=>link},preventDefault(){this.defaultPrevented=true}};
  events.click(click);
  assert.ok(click.defaultPrevented);
  assert.equal(submit(editor).defaultPrevented,undefined); // Saving never asks to discard.
  prevented=false;
  windowEvents.beforeunload({preventDefault(){prevented=true}});
  assert.equal(prevented,false);
  windowEvents.pageshow();
  accept=true;
  assert.equal(submit({}).defaultPrevented,undefined);
}
console.log('Unsaved input guard regression checks passed.');
