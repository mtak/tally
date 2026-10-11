(() => {
  function setup() {
    document.querySelectorAll('[data-flow-entry]').forEach(entry => {
      const mode = entry.querySelector('[name$="-flow_mode"]');
      const check = entry.querySelector('[name$="-no_flows"]');
      const amounts = ['inflow', 'outflow'].map(key => entry.querySelector(`[name$="-${key}"]`));
      const update = () => {
        entry.querySelector('[data-flow-period]').hidden = mode.value === 'cumulative';
        entry.querySelector('[data-flow-cumulative]').hidden = mode.value !== 'cumulative';
        entry.querySelectorAll('[data-flow-period] input, [data-flow-period] select').forEach(input => {input.disabled = mode.value === 'cumulative';});
        entry.querySelectorAll('[data-flow-cumulative] input, [data-flow-cumulative] select').forEach(input => {input.disabled = mode.value !== 'cumulative';});
      };
      mode.addEventListener('change', update);
      check.addEventListener('change', () => { if (check.checked) amounts.forEach(input => {input.value = '0';}); });
      amounts.forEach(input => input.addEventListener('input', () => {check.checked = false;}));
      update();
    });
  }
  setup();
})();
