// static/js/chat.js
document.addEventListener('DOMContentLoaded', function() {
    console.log('Chat interface loaded');
    
    // Chat functionality
    const messageForm = document.getElementById('message-form');
    const messageInput = document.getElementById('message-input');
    const chatMessages = document.getElementById('chat-messages');
    const roomLinks = document.querySelectorAll('.room-link');
    const currentRoomElement = document.getElementById('current-room');
    const onlineUsersList = document.getElementById('online-users-list');
    const onlineCountElement = document.getElementById('online-count');
    const userCountElement = document.getElementById('user-count');
    const searchToggle = document.getElementById('search-toggle');
    const searchBox = document.getElementById('search-box');
    const searchInput = document.getElementById('search-input');
    const searchBtn = document.getElementById('search-btn');
    
    // Check if file upload elements exist before using them
    let fileUploadBtn, imageUpload, videoUpload, audioUpload, filePreview, fileName, removeFileBtn;
    let voiceRecorder, startRecordingBtn, stopRecordingBtn, recordingTimer, recordedAudio;
    
    try {
        fileUploadBtn = document.getElementById('file-upload-btn');
        imageUpload = document.getElementById('image-upload');
        videoUpload = document.getElementById('video-upload');
        audioUpload = document.getElementById('audio-upload');
        filePreview = document.getElementById('file-preview');
        fileName = document.getElementById('file-name');
        removeFileBtn = document.getElementById('remove-file');
        voiceRecorder = document.getElementById('voice-recorder');
        startRecordingBtn = document.getElementById('start-recording');
        stopRecordingBtn = document.getElementById('stop-recording');
        recordingTimer = document.getElementById('recording-timer');
        recordedAudio = document.getElementById('recorded-audio');
    } catch (e) {
        console.log('File upload elements not found:', e);
    }
    
    let currentRoom = null;
    let messagePolling = null;
    let currentUsername = document.body.dataset.username;
    let currentFile = null;
    let currentFileType = null;
    
    // Function to load messages for a room
    function loadMessages(room) {
        console.log('Loading messages for room:', room);
        fetch(`/get_messages/${room}?limit=50`)
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(messages => {
                chatMessages.innerHTML = '';
                if (messages.length === 0) {
                    chatMessages.innerHTML = `
                        <div class="text-center text-muted mt-5">
                            <i class="fas fa-comments fa-3x mb-3"></i>
                            <p>No messages yet. Start the conversation!</p>
                        </div>
                    `;
                } else {
                    messages.forEach(message => {
                        addMessageToChat(message);
                    });
                }
                chatMessages.scrollTop = chatMessages.scrollHeight;
            })
            .catch(error => {
                console.error('Error loading messages:', error);
                chatMessages.innerHTML = `
                    <div class="text-center text-muted mt-5">
                        <i class="fas fa-exclamation-triangle fa-3x mb-3"></i>
                        <p>Error loading messages. Please try again.</p>
                    </div>
                `;
            });
    }
    
    // Function to add a message to the chat
    function addMessageToChat(message) {
        const isCurrentUser = message.username === currentUsername;
        const messageClass = isCurrentUser ? 'message-sent' : 'message-received';
        
        const messageElement = document.createElement('div');
        messageElement.classList.add('message-bubble', messageClass);
        
        let messageContent = '';
        if (message.message_type === 'image') {
            messageContent = `<img src="${message.message}" class="img-fluid rounded" alt="Shared image" style="max-height: 300px;">`;
        } else if (message.message_type === 'video') {
            messageContent = `
                <video controls class="img-fluid rounded" style="max-height: 300px;">
                    <source src="${message.message}" type="video/mp4">
                    Your browser does not support the video tag.
                </video>
            `;
        } else if (message.message_type === 'audio') {
            messageContent = `
                <audio controls class="w-100">
                    <source src="${message.message}" type="audio/mpeg">
                    Your browser does not support the audio element.
                </audio>
            `;
        } else {
            messageContent = `<div class="message-content">${escapeHtml(message.message)}</div>`;
        }
        
        messageElement.innerHTML = `
            <div class="d-flex justify-content-between align-items-start">
                <strong>${isCurrentUser ? 'You' : message.username}</strong>
                <small class="message-time">${formatTime(message.timestamp)}</small>
            </div>
            ${messageContent}
        `;
        
        chatMessages.appendChild(messageElement);
    }
    
    // Helper function to format time
    function formatTime(timestamp) {
        try {
            const date = new Date(timestamp);
            return date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        } catch (e) {
            return timestamp;
        }
    }
    
    // Helper function to escape HTML
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Function to update online users
    function updateOnlineUsers() {
        fetch('/get_online_users')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(users => {
                onlineUsersList.innerHTML = '';
                onlineCountElement.textContent = users.length;
                
                // Filter out current user from online users list
                const otherUsers = users.filter(user => user.username !== currentUsername);
                userCountElement.textContent = `${otherUsers.length + 1} users`; // +1 for current user
                
                // Add current user first
                const currentUserElement = document.createElement('div');
                currentUserElement.classList.add('d-flex', 'align-items-center', 'mb-2');
                currentUserElement.innerHTML = `
                    <span class="online-indicator"></span>
                    You (${document.body.dataset.role || 'user'})
                `;
                onlineUsersList.appendChild(currentUserElement);
                
                // Add other users
                otherUsers.forEach(user => {
                    const userElement = document.createElement('div');
                    userElement.classList.add('d-flex', 'align-items-center', 'mb-2');
                    userElement.innerHTML = `
                        <span class="online-indicator"></span>
                        ${user.username} <span class="badge bg-secondary ms-2">${user.role}</span>
                    `;
                    onlineUsersList.appendChild(userElement);
                });
            })
            .catch(error => {
                console.error('Error fetching online users:', error);
            });
    }
    
    // Handle room selection
    roomLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Update active room
            roomLinks.forEach(r => r.classList.remove('active'));
            this.classList.add('active');
            
            // Set current room
            currentRoom = this.dataset.room;
            const roomDescription = this.querySelector('small').textContent;
            currentRoomElement.textContent = roomDescription;
            
            // Enable message input
            messageInput.disabled = false;
            messageForm.querySelector('button').disabled = false;
            
            // Enable file upload if elements exist
            if (fileUploadBtn) fileUploadBtn.disabled = false;
            if (imageUpload) imageUpload.disabled = false;
            if (videoUpload) videoUpload.disabled = false;
            if (audioUpload) audioUpload.disabled = false;
            
            // Load messages for the room
            loadMessages(currentRoom);
            
            // Start polling for new messages
            if (messagePolling) {
                clearInterval(messagePolling);
            }
            
            messagePolling = setInterval(() => {
                if (!currentRoom) return;
                
                fetch(`/get_messages/${currentRoom}?limit=1`)
                    .then(response => response.json())
                    .then(messages => {
                        if (messages.length > 0) {
                            const lastMessage = messages[messages.length - 1];
                            // Check if this message is already displayed
                            const existingMessages = chatMessages.querySelectorAll('.message-bubble');
                            const lastDisplayed = existingMessages[existingMessages.length - 1];
                            
                            if (!lastDisplayed || 
                                !lastDisplayed.querySelector('.message-time').textContent.includes(
                                    formatTime(lastMessage.timestamp))) {
                                addMessageToChat(lastMessage);
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            }
                        }
                    })
                    .catch(error => {
                        console.error('Error polling for messages:', error);
                    });
            }, 3000);
        });
    });
    
    // Handle message submission
    messageForm.addEventListener('submit', function(e) {
        e.preventDefault();
        console.log('Submit button clicked');
        
        if ((messageInput.value.trim() === '' && !currentFile) || !currentRoom) {
            console.log('Cannot send: no message content or no room selected');
            return;
        }
        
        const formData = new FormData();
        formData.append('room', currentRoom);
        formData.append('message_type', currentFileType || 'text');
        
        if (currentFile) {
            formData.append('file', currentFile);
            // For file uploads, the message can be optional
            if (messageInput.value.trim()) {
                formData.append('message', messageInput.value.trim());
            }
        } else {
            formData.append('message', messageInput.value.trim());
        }
        
        console.log('Sending message to server');
        
        fetch('/send_message', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            console.log('Server response:', data);
            if (data.status === 'success') {
                messageInput.value = '';
                if (currentFile) {
                    clearFileSelection();
                }
                // Scroll to bottom after sending message
                setTimeout(() => {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }, 100);
            } else {
                alert('Error sending message: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error sending message:', error);
            alert('Error sending message. Please check console for details.');
        });
    });
    
    // File upload handling functions (only if elements exist)
    if (fileUploadBtn && imageUpload && videoUpload && audioUpload && filePreview && fileName && removeFileBtn) {
        function handleFileUpload(file, type) {
            currentFile = file;
            currentFileType = type;
            fileName.textContent = file.name;
            filePreview.classList.remove('d-none');
            
            // Enable submit button if there's a file
            messageForm.querySelector('button').disabled = false;
        }
        
        function clearFileSelection() {
            currentFile = null;
            currentFileType = null;
            filePreview.classList.add('d-none');
            imageUpload.value = '';
            videoUpload.value = '';
            audioUpload.value = '';
            if (recordedAudio) recordedAudio.classList.add('d-none');
            if (voiceRecorder) voiceRecorder.classList.add('d-none');
        }
        
        imageUpload.addEventListener('change', function(e) {
            if (this.files.length > 0) {
                handleFileUpload(this.files[0], 'image');
            }
        });
        
        videoUpload.addEventListener('change', function(e) {
            if (this.files.length > 0) {
                handleFileUpload(this.files[0], 'video');
            }
        });
        
        audioUpload.addEventListener('change', function(e) {
            if (this.files.length > 0) {
                handleFileUpload(this.files[0], 'audio');
            }
        });
        
        removeFileBtn.addEventListener('click', clearFileSelection);
    }
    
    // Voice recording functionality (only if elements exist)
    if (voiceRecorder && startRecordingBtn && stopRecordingBtn && recordingTimer && recordedAudio) {
        let mediaRecorder = null;
        let audioChunks = [];
        let recordingInterval = null;
        let recordingSeconds = 0;
        
        startRecordingBtn.addEventListener('click', function() {
            if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                navigator.mediaDevices.getUserMedia({ audio: true })
                    .then(function(stream) {
                        mediaRecorder = new MediaRecorder(stream);
                        audioChunks = [];
                        
                        mediaRecorder.ondataavailable = function(e) {
                            audioChunks.push(e.data);
                        };
                        
                        mediaRecorder.onstop = function() {
                            const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                            currentFile = audioBlob;
                            currentFileType = 'audio';
                            fileName.textContent = 'Voice recording.wav';
                            filePreview.classList.remove('d-none');
                            
                            const audioURL = URL.createObjectURL(audioBlob);
                            recordedAudio.src = audioURL;
                            recordedAudio.classList.remove('d-none');
                            
                            // Enable submit button
                            messageForm.querySelector('button').disabled = false;
                        };
                        
                        mediaRecorder.start();
                        startRecordingBtn.classList.add('d-none');
                        stopRecordingBtn.classList.remove('d-none');
                        
                        // Start timer
                        recordingSeconds = 0;
                        recordingInterval = setInterval(function() {
                            recordingSeconds++;
                            const minutes = Math.floor(recordingSeconds / 60);
                            const seconds = recordingSeconds % 60;
                            recordingTimer.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
                        }, 1000);
                    })
                    .catch(function(err) {
                        console.error('Error accessing microphone:', err);
                        alert('Cannot access microphone. Please check permissions.');
                    });
            } else {
                alert('Your browser does not support audio recording.');
            }
        });
        
        stopRecordingBtn.addEventListener('click', function() {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
                
                startRecordingBtn.classList.remove('d-none');
                stopRecordingBtn.classList.add('d-none');
                
                // Stop timer
                clearInterval(recordingInterval);
                recordingTimer.textContent = '00:00';
            }
        });
        
        // Toggle voice recorder
        document.querySelector('.dropdown-item[for="audio-upload"]').addEventListener('click', function(e) {
            e.preventDefault();
            voiceRecorder.classList.toggle('d-none');
        });
    }
    
    // Toggle search box
    if (searchToggle && searchBox) {
        searchToggle.addEventListener('click', function() {
            searchBox.classList.toggle('d-none');
        });
    }
    
    // Handle search
    if (searchBtn && searchInput) {
        searchBtn.addEventListener('click', function() {
            const query = searchInput.value.trim();
            if (query === '' || !currentRoom) return;
            
            fetch(`/search_messages?q=${encodeURIComponent(query)}&room=${currentRoom}`)
                .then(response => response.json())
                .then(results => {
                    chatMessages.innerHTML = '';
                    if (results.length === 0) {
                        chatMessages.innerHTML = `
                            <div class="text-center text-muted mt-5">
                                <i class="fas fa-search fa-3x mb-3"></i>
                                <p>No results found for "${query}"</p>
                            </div>
                        `;
                    } else {
                        results.forEach(message => {
                            addMessageToChat(message);
                        });
                    }
                })
                .catch(error => {
                    console.error('Error searching messages:', error);
                });
        });
    }
    
    // Initial update of online users
    updateOnlineUsers();
    setInterval(updateOnlineUsers, 10000);
});