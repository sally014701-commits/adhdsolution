function sendTabInfo(url, title) {
    fetch('http://localhost:5000/update_tab', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url, title: title || '' })
    }).catch(err => {
        // 서버가 꺼져있을 때의 에러 무시
        console.debug("Focus tracker server is not running.", err);
    });
}

// 탭 전환 시 현재 URL 출력 및 서버 전송
chrome.tabs.onActivated.addListener((activeInfo) => {
    chrome.tabs.get(activeInfo.tabId, (tab) => {
        if (tab && tab.url) {
            console.log("Tab activated:", tab.url);
            sendTabInfo(tab.url, tab.title);
        }
    });
});

// 페이지 로드 시 URL 출력 및 서버 전송
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === 'complete' && tab && tab.url) {
        console.log("Tab updated:", tab.url);
        sendTabInfo(tab.url, tab.title);
    }
});
