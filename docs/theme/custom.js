// COTA 文档自定义JavaScript

// 添加代码复制功能
document.addEventListener('DOMContentLoaded', function() {
    // 为所有代码块添加复制按钮
    const codeBlocks = document.querySelectorAll('pre code');
    
    codeBlocks.forEach(function(codeBlock) {
        const pre = codeBlock.parentNode;
        const button = document.createElement('button');
        button.className = 'copy-button';
        button.textContent = '复制';
        button.style.cssText = `
            position: absolute;
            top: 5px;
            right: 5px;
            padding: 4px 8px;
            background: #007acc;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
            z-index: 1;
        `;
        
        pre.style.position = 'relative';
        pre.appendChild(button);
        
        button.addEventListener('click', function() {
            navigator.clipboard.writeText(codeBlock.textContent).then(function() {
                button.textContent = '已复制!';
                setTimeout(function() {
                    button.textContent = '复制';
                }, 2000);
            });
        });
    });
    
    // 添加外链图标
    const externalLinks = document.querySelectorAll('a[href^="http"]:not([href*="' + window.location.hostname + '"])');
    externalLinks.forEach(function(link) {
        link.innerHTML += ' <i class="fa fa-external-link" style="font-size: 0.8em; margin-left: 0.2em;"></i>';
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
    });
});

// 改进搜索体验
if (window.elasticlunr) {
    // 自定义搜索权重
    console.log('Search engine loaded with custom weights');
}
