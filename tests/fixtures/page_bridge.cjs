// One fake page in a Node process: each stdin line is {"expression"}, evaluated in global scope like
// Runtime.evaluate with returnByValue and awaitPromise; each stdout line is {"value"}, {} for undefined, or
// {"exception"}. The DOM adapter module and its JSON config are the two arguments; `dom` holds its handles.
const createDOM = require(process.argv[2]);
global.dom = createDOM(JSON.parse(process.argv[3]));
const lines = require('node:readline').createInterface({input: process.stdin});
let queue = Promise.resolve();
lines.on('line', line => {
  queue = queue.then(async () => {
    let reply;
    try {
      const value = await (0, eval)(JSON.parse(line).expression);
      reply = value === undefined ? {} : {value: JSON.parse(JSON.stringify(value))};
    } catch (error) {
      reply = {exception: String(error?.stack || error)};
    }
    process.stdout.write(JSON.stringify(reply) + '\n');
  });
});
