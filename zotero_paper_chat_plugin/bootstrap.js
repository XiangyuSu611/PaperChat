var PaperChatServices =
  typeof Services !== "undefined"
    ? Services
    : ChromeUtils.import("resource://gre/modules/Services.jsm").Services;

var PaperChatPlugin = {
  id: "paper-chat@local",
  menuItemID: "paper-chat-open-menuitem",
  toolbarButtonID: "paper-chat-toolbar-button",
  baseURL: "http://127.0.0.1:8766",
  windows: new Set(),
  lastOpenAt: 0,

  log(message) {
    Zotero.debug(`[Paper Chat] ${message}`);
  },

  install() {},

  uninstall() {},

  startup({ id }) {
    this.id = id || this.id;
    for (const win of PaperChatServices.wm.getEnumerator("navigator:browser")) {
      if (win.ZoteroPane) {
        this.onMainWindowLoad({ window: win });
      }
    }
  },

  shutdown() {
    for (const win of Array.from(this.windows)) {
      this.onMainWindowUnload({ window: win });
    }
    this.windows.clear();
  },

  onMainWindowLoad({ window }) {
    if (!window?.ZoteroPane || this.windows.has(window)) return;
    this.windows.add(window);
    this.addItemContextMenu(window);
    this.addToolbarButton(window);
  },

  onMainWindowUnload({ window }) {
    this.removeItemContextMenu(window);
    this.removeToolbarButton(window);
    this.windows.delete(window);
  },

  addItemContextMenu(win) {
    const doc = win.document;
    const menu = doc.getElementById("zotero-itemmenu");
    if (!menu || doc.getElementById(this.menuItemID)) return;

    const menuItem = doc.createXULElement
      ? doc.createXULElement("menuitem")
      : doc.createElement("menuitem");
    menuItem.id = this.menuItemID;
    menuItem.setAttribute("label", "Open in Paper Chat");
    menuItem.addEventListener("command", () => this.openSelectedItem(win));
    menu.appendChild(menuItem);
  },

  removeItemContextMenu(win) {
    const item = win.document.getElementById(this.menuItemID);
    item?.remove();
  },

  addToolbarButton(win) {
    const doc = win.document;
    if (doc.getElementById(this.toolbarButtonID)) return;

    const toolbar =
      doc.getElementById("zotero-items-toolbar") ||
      doc.getElementById("zotero-toolbar") ||
      doc.querySelector("toolbar");
    if (!toolbar) {
      this.log("Could not find a Zotero toolbar; context menu is still available.");
      return;
    }

    const button = doc.createXULElement
      ? doc.createXULElement("toolbarbutton")
      : doc.createElement("button");
    button.id = this.toolbarButtonID;
    button.setAttribute("label", "Paper Chat");
    button.setAttribute("tooltiptext", "Open selected item in Paper Chat");
    button.setAttribute("class", "toolbarbutton-1");
    button.addEventListener("command", () => this.openSelectedItem(win));
    button.addEventListener("click", () => this.openSelectedItem(win));
    toolbar.appendChild(button);
  },

  removeToolbarButton(win) {
    const button = win.document.getElementById(this.toolbarButtonID);
    button?.remove();
  },

  getSelectedRegularItem(win) {
    const selected = win.ZoteroPane.getSelectedItems();
    if (!selected?.length) return null;
    let item = selected[0];
    if (item.isAttachment?.() && item.parentItemID) {
      item = Zotero.Items.get(item.parentItemID);
    }
    return item;
  },

  openSelectedItem(win) {
    const now = Date.now();
    if (now - this.lastOpenAt < 500) return;
    this.lastOpenAt = now;

    const item = this.getSelectedRegularItem(win);
    if (!item?.key) {
      win.alert("Select a Zotero item or PDF attachment first.");
      return;
    }
    const url = `${this.baseURL}/?paper=${encodeURIComponent(item.key)}`;
    Zotero.launchURL(url);
  },
};

function install(data, reason) {
  PaperChatPlugin.install(data, reason);
}

function uninstall(data, reason) {
  PaperChatPlugin.uninstall(data, reason);
}

function startup(data, reason) {
  PaperChatPlugin.startup(data, reason);
}

function shutdown(data, reason) {
  PaperChatPlugin.shutdown(data, reason);
}

function onMainWindowLoad(data) {
  PaperChatPlugin.onMainWindowLoad(data);
}

function onMainWindowUnload(data) {
  PaperChatPlugin.onMainWindowUnload(data);
}
