import {api} from "./api.js";

// Controller owns requests/state; render receives a snapshot and only updates the UI.
export class TaskList {
  constructor(render) {
    this.render = render;
    this.generation = 0;
    this.controller = null;
    this.state = {items: [], phase: "empty", nextOffset: null, filter: "", message: ""};
    this.retryAppend = false;
  }

  async load(append = false) {
    if (append && this.state.nextOffset === null) return;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const generation = ++this.generation;
    const offset = append ? this.state.nextOffset : 0;
    this.retryAppend = append;
    this.state = {...this.state, items: append ? this.state.items : [], phase: "loading", message: ""};
    this.render(this.state);
    const params = new URLSearchParams({limit: "5", offset: String(offset)});
    if (this.state.filter) params.set("status", this.state.filter);
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const page = await api(`/api/tasks?${params}`, {signal: controller.signal});
      if (generation !== this.generation) return;
      const items = append ? [...this.state.items, ...page.items] : page.items;
      this.state = {...this.state, items, nextOffset: page.next_offset,
                    phase: items.length ? "success" : "empty", message: ""};
    } catch (error) {
      if (generation !== this.generation) return;
      this.state = {...this.state, phase: this.state.items.length ? "partial" : "error",
                    message: error.name === "AbortError" ? "Время ожидания истекло" : error.message};
    } finally {
      clearTimeout(timer);
      if (generation === this.generation) this.render(this.state);
    }
  }

  setFilter(filter) {
    this.state = {...this.state, filter, nextOffset: null};
    return this.load();
  }

  retry() { return this.load(this.retryAppend); }

  dispose() {
    ++this.generation;
    this.controller?.abort();
    this.state = {...this.state, items: [], nextOffset: null, phase: "empty"};
  }
}
