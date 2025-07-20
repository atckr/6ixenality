/*
 * Copyright (c) 2024, BlackBerry Limited. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <time.h>
#include <termios.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <errno.h>
#include <pthread.h>
#include <sys/time.h>

#include <camera/camera_api.h>
#include "rainbowhat.h"

/**
 * @brief Number of channels for supported frametypes
 */
#define NUM_CHANNELS (3)

/**
 * @brief Maximum number of frames to buffer during recording
 */
#define MAX_FRAME_BUFFER 1000

/**
 * @brief Server configuration for sending data
 */
#define SERVER_IP "192.168.1.100"  // Update with your processing server IP
#define SERVER_PORT 8080

/**
 * @brief List of frametypes that @c processCameraData can operate on
 */
const camera_frametype_t cSupportedFrametypes[] = {
    CAMERA_FRAMETYPE_YCBYCR,
    CAMERA_FRAMETYPE_CBYCRY,
    CAMERA_FRAMETYPE_RGB8888,
    CAMERA_FRAMETYPE_BGR8888,
};
#define NUM_SUPPORTED_FRAMETYPES (sizeof(cSupportedFrametypes) / sizeof(cSupportedFrametypes[0]))

/**
 * @brief Structure to hold frame data during recording
 */
typedef struct {
    uint8_t* data;
    size_t size;
    struct timeval timestamp;
} frame_data_t;

/**
 * @brief Structure to hold environment data
 */
typedef struct {
    double temperature;
    double pressure;
    struct timeval button_press_time;
    struct timeval button_release_time;
    bool is_recording;
} environment_data_t;

/**
 * @brief Global variables for recording state
 */
static bool g_recording = false;
static frame_data_t g_frame_buffer[MAX_FRAME_BUFFER];
static int g_frame_count = 0;
static environment_data_t g_env_data;
static pthread_mutex_t g_recording_mutex = PTHREAD_MUTEX_INITIALIZER;
static camera_handle_t g_camera_handle = CAMERA_HANDLE_INVALID;

/**
 * @brief Function prototypes
 */
static void listAvailableCameras(void);
static void processCameraData(camera_handle_t handle, camera_buffer_t* buffer, void* arg);
static void* buttonMonitorThread(void* arg);
static int sendDataToServer(void);
static int receiveAnalysisResult(int socket_fd, char* result);
static void displayResult(const char* result);
static void initializeHardware(void);
static void cleanupHardware(void);

int main(int argc, char* argv[])
{
    int err;
    int opt;
    camera_unit_t unit = CAMERA_UNIT_NONE;
    camera_frametype_t frametype = CAMERA_FRAMETYPE_UNSPECIFIED;
    pthread_t button_thread;

    // Read command line options
    while ((opt = getopt(argc, argv, "u:")) != -1 || (optind < argc)) {
        switch (opt) {
        case 'u':
            unit = (camera_unit_t)strtol(optarg, NULL, 10);
            break;
        default:
            printf("Ignoring unrecognized option: %s\n", optarg);
            break;
        }
    }

    // If no camera unit has been specified, list the options and exit
    if ((unit == CAMERA_UNIT_NONE) || (unit >= CAMERA_UNIT_NUM_UNITS)) {
        listAvailableCameras();
        printf("Please provide camera unit with -u option\n");
        exit(EXIT_SUCCESS);
    }

    // Initialize Rainbow HAT hardware
    printf("Initializing Rainbow HAT hardware...\n");
    if (initializeHardware() != 0) {
        printf("Failed to initialize Rainbow HAT hardware\n");
        exit(EXIT_FAILURE);
    }

    // Open a read-only handle for the specified camera unit
    err = camera_open(unit, CAMERA_MODE_RO, &g_camera_handle);
    if ((err != CAMERA_EOK) || (g_camera_handle == CAMERA_HANDLE_INVALID)) {
        printf("Failed to open CAMERA_UNIT_%d: err = %d\n", (int)unit, err);
        cleanupHardware();
        exit(EXIT_FAILURE);
    }

    // Make sure that this camera defaults to a supported frametype
    err = camera_get_vf_property(g_camera_handle, CAMERA_IMGPROP_FORMAT, &frametype);
    if (err != CAMERA_EOK) {
        printf("Failed to get frametype for CAMERA_UNIT_%d: err = %d\n", (int)unit, err);
        camera_close(g_camera_handle);
        cleanupHardware();
        exit(EXIT_FAILURE);
    }

    bool unsupportedFrametype = true;
    for (uint i = 0; i < NUM_SUPPORTED_FRAMETYPES; i++) {
        if (frametype == cSupportedFrametypes[i]) {
            unsupportedFrametype = false;
            break;
        }
    }
    if (unsupportedFrametype) {
        printf("Camera frametype %d is not supported\n", (int)frametype);
        camera_close(g_camera_handle);
        cleanupHardware();
        exit(EXIT_FAILURE);
    }

    // Initialize environment data structure
    memset(&g_env_data, 0, sizeof(g_env_data));

    // Start the camera streaming
    err = camera_start_viewfinder(g_camera_handle, processCameraData, NULL, NULL);
    if (err != CAMERA_EOK) {
        printf("Failed to start CAMERA_UNIT_%d: err = %d\n", (int)unit, err);
        camera_close(g_camera_handle);
        cleanupHardware();
        exit(EXIT_FAILURE);
    }

    // Start button monitoring thread
    if (pthread_create(&button_thread, NULL, buttonMonitorThread, NULL) != 0) {
        printf("Failed to create button monitoring thread\n");
        camera_stop_viewfinder(g_camera_handle);
        camera_close(g_camera_handle);
        cleanupHardware();
        exit(EXIT_FAILURE);
    }

    printf("System ready. Press Button A to start recording, Button B to stop and send data.\n");
    printf("Press any key to exit...\n");

    // Wait for user input to exit
    getchar();

    // Cleanup
    pthread_cancel(button_thread);
    pthread_join(button_thread, NULL);

    camera_stop_viewfinder(g_camera_handle);
    camera_close(g_camera_handle);
    cleanupHardware();

    printf("System shut down successfully.\n");
    return 0;
}

static void initializeHardware(void)
{
    // Initialize GPIO
    if (init_gpio() != RH_SUCCESS) {
        fprintf(stderr, "Failed to initialize GPIO\n");
        exit(EXIT_FAILURE);
    }

    // Initialize LEDs
    init_led(Led_RED);
    init_led(Led_GREEN);
    init_led(Led_BLUE);

    // Initialize buttons
    init_button(Button_A);
    init_button(Button_B);
    init_button(Button_C);

    // Initialize BMP280 sensor
    if (init_bmp() != RH_SUCCESS) {
        fprintf(stderr, "Failed to initialize BMP280 sensor\n");
        exit(EXIT_FAILURE);
    }

    // Initialize alphanumeric display
    if (init_alphanum() != RH_SUCCESS) {
        fprintf(stderr, "Failed to initialize alphanumeric display\n");
        exit(EXIT_FAILURE);
    }

    // Initialize RGB LEDs
    init_rgb_led();

    // Display ready message
    set_alphanum_string("RDY");
    show_alphanum();

    // Set RGB LEDs to indicate ready state (blue)
    for (int i = 0; i < 7; i++) {
        set_rgb_led(i, 0, 0, 255, 30);
    }
    show_rgb_leds();
}

static void cleanupHardware(void)
{
    // Turn off all LEDs
    set_led(Led_RED, false);
    set_led(Led_GREEN, false);
    set_led(Led_BLUE, false);
    
    clear_rbg_leds();
    clear_alphanum();
}

static void* buttonMonitorThread(void* arg)
{
    bool button_a_prev = false;
    bool button_b_prev = false;
    bool button_a_current, button_b_current;

    (void)arg; // Suppress unused parameter warning

    while (1) {
        button_a_current = read_button(Button_A);
        button_b_current = read_button(Button_B);

        // Button A pressed (start recording)
        if (button_a_current && !button_a_prev && !g_recording) {
            pthread_mutex_lock(&g_recording_mutex);
            
            printf("Button A pressed - Starting recording\n");
            gettimeofday(&g_env_data.button_press_time, NULL);
            
            // Get current environment data
            if (get_bmp_data(&g_env_data.temperature, &g_env_data.pressure) != RH_SUCCESS) {
                printf("Warning: Failed to read environment data\n");
                g_env_data.temperature = 0.0;
                g_env_data.pressure = 0.0;
            }
            
            g_recording = true;
            g_env_data.is_recording = true;
            g_frame_count = 0;
            
            // Visual feedback - red LED and display
            set_led(Led_RED, true);
            set_led(Led_GREEN, false);
            set_alphanum_string("REC");
            show_alphanum();
            
            // Set RGB LEDs to red for recording
            for (int i = 0; i < 7; i++) {
                set_rgb_led(i, 255, 0, 0, 50);
            }
            show_rgb_leds();
            
            pthread_mutex_unlock(&g_recording_mutex);
        }

        // Button A released
        if (!button_a_current && button_a_prev && g_recording) {
            pthread_mutex_lock(&g_recording_mutex);
            gettimeofday(&g_env_data.button_release_time, NULL);
            pthread_mutex_unlock(&g_recording_mutex);
            printf("Button A released\n");
        }

        // Button B pressed (stop recording and send data)
        if (button_b_current && !button_b_prev && g_recording) {
            pthread_mutex_lock(&g_recording_mutex);
            
            printf("Button B pressed - Stopping recording and sending data\n");
            g_recording = false;
            g_env_data.is_recording = false;
            
            // Visual feedback - yellow LED and display
            set_led(Led_RED, true);
            set_led(Led_GREEN, true);
            set_alphanum_string("SEND");
            show_alphanum();
            
            // Set RGB LEDs to yellow for processing
            for (int i = 0; i < 7; i++) {
                set_rgb_led(i, 255, 255, 0, 50);
            }
            show_rgb_leds();
            
            pthread_mutex_unlock(&g_recording_mutex);
            
            // Send data to server in separate thread or blocking call
            if (sendDataToServer() == 0) {
                printf("Data sent successfully, waiting for analysis result...\n");
            } else {
                printf("Failed to send data to server\n");
                // Display error
                set_alphanum_string("ERR");
                show_alphanum();
                set_led(Led_RED, true);
                set_led(Led_GREEN, false);
            }
        }

        button_a_prev = button_a_current;
        button_b_prev = button_b_current;
        
        usleep(50000); // 50ms polling interval
    }

    return NULL;
}

static void processCameraData(camera_handle_t handle, camera_buffer_t* buffer, void* arg)
{
    (void)handle;
    (void)arg;

    pthread_mutex_lock(&g_recording_mutex);
    
    if (g_recording && g_frame_count < MAX_FRAME_BUFFER) {
        // Calculate buffer size based on frametype
        size_t buffer_size = 0;
        
        switch (buffer->frametype) {
        case CAMERA_FRAMETYPE_RGB8888:
            buffer_size = buffer->framedesc.rgb8888.height * buffer->framedesc.rgb8888.stride;
            break;
        case CAMERA_FRAMETYPE_BGR8888:
            buffer_size = buffer->framedesc.bgr8888.height * buffer->framedesc.bgr8888.stride;
            break;
        case CAMERA_FRAMETYPE_YCBYCR:
            buffer_size = buffer->framedesc.ycbycr.height * buffer->framedesc.ycbycr.stride;
            break;
        case CAMERA_FRAMETYPE_CBYCRY:
            buffer_size = buffer->framedesc.cbycry.height * buffer->framedesc.cbycry.stride;
            break;
        default:
            pthread_mutex_unlock(&g_recording_mutex);
            return;
        }
        
        // Allocate memory for frame data
        g_frame_buffer[g_frame_count].data = malloc(buffer_size);
        if (g_frame_buffer[g_frame_count].data != NULL) {
            memcpy(g_frame_buffer[g_frame_count].data, buffer->framebuf, buffer_size);
            g_frame_buffer[g_frame_count].size = buffer_size;
            gettimeofday(&g_frame_buffer[g_frame_count].timestamp, NULL);
            g_frame_count++;
            
            // Update frame count display
            char frame_str[5];
            snprintf(frame_str, sizeof(frame_str), "%04d", g_frame_count);
            set_alphanum_string(frame_str);
            show_alphanum();
        } else {
            printf("Failed to allocate memory for frame %d\n", g_frame_count);
        }
    }
    
    pthread_mutex_unlock(&g_recording_mutex);
}

static int sendDataToServer(void)
{
    int socket_fd;
    struct sockaddr_in server_addr;
    char result[5] = {0};

    // Create socket
    socket_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (socket_fd < 0) {
        printf("Failed to create socket: %s\n", strerror(errno));
        return -1;
    }

    // Configure server address
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(SERVER_PORT);
    if (inet_pton(AF_INET, SERVER_IP, &server_addr.sin_addr) <= 0) {
        printf("Invalid server IP address\n");
        close(socket_fd);
        return -1;
    }

    // Connect to server
    if (connect(socket_fd, (struct sockaddr*)&server_addr, sizeof(server_addr)) < 0) {
        printf("Failed to connect to server: %s\n", strerror(errno));
        close(socket_fd);
        return -1;
    }

    // Send metadata first
    if (send(socket_fd, &g_env_data, sizeof(g_env_data), 0) < 0) {
        printf("Failed to send environment data: %s\n", strerror(errno));
        close(socket_fd);
        return -1;
    }

    // Send frame count
    if (send(socket_fd, &g_frame_count, sizeof(g_frame_count), 0) < 0) {
        printf("Failed to send frame count: %s\n", strerror(errno));
        close(socket_fd);
        return -1;
    }

    // Send frame data
    for (int i = 0; i < g_frame_count; i++) {
        // Send frame size first
        if (send(socket_fd, &g_frame_buffer[i].size, sizeof(g_frame_buffer[i].size), 0) < 0) {
            printf("Failed to send frame size: %s\n", strerror(errno));
            close(socket_fd);
            return -1;
        }
        
        // Send timestamp
        if (send(socket_fd, &g_frame_buffer[i].timestamp, sizeof(g_frame_buffer[i].timestamp), 0) < 0) {
            printf("Failed to send frame timestamp: %s\n", strerror(errno));
            close(socket_fd);
            return -1;
        }
        
        // Send frame data
        if (send(socket_fd, g_frame_buffer[i].data, g_frame_buffer[i].size, 0) < 0) {
            printf("Failed to send frame data: %s\n", strerror(errno));
            close(socket_fd);
            return -1;
        }
        
        // Free the frame data after sending
        free(g_frame_buffer[i].data);
        g_frame_buffer[i].data = NULL;
    }

    printf("All data sent successfully, waiting for analysis result...\n");

    // Receive analysis result
    if (receiveAnalysisResult(socket_fd, result) == 0) {
        displayResult(result);
    }

    close(socket_fd);
    return 0;
}

static int receiveAnalysisResult(int socket_fd, char* result)
{
    int bytes_received = recv(socket_fd, result, 4, 0);
    if (bytes_received < 0) {
        printf("Failed to receive analysis result: %s\n", strerror(errno));
        return -1;
    }
    
    if (bytes_received != 4) {
        printf("Received incomplete analysis result\n");
        return -1;
    }
    
    result[4] = '\0'; // Null terminate
    printf("Received analysis result: %s\n", result);
    return 0;
}

static void displayResult(const char* result)
{
    // Display result on alphanumeric display
    set_alphanum_string(result);
    show_alphanum();
    
    // Set RGB LEDs to green for success
    for (int i = 0; i < 7; i++) {
        set_rgb_led(i, 0, 255, 0, 50);
    }
    show_rgb_leds();
    
    // Set green LED
    set_led(Led_RED, false);
    set_led(Led_GREEN, true);
    set_led(Led_BLUE, false);
    
    printf("Analysis result displayed: %s\n", result);
}

static void listAvailableCameras(void)
{
    int err;
    uint numSupported;
    camera_unit_t* supportedCameras;

    // Determine how many cameras are supported
    err = camera_get_supported_cameras(0, &numSupported, NULL);
    if (err != CAMERA_EOK) {
        printf("Failed to get number of supported cameras: err = %d\n", err);
        return;
    }

    if (numSupported == 0) {
        printf("No supported cameras detected!\n");
        return;
    }

    // Allocate an array big enough to hold all camera units
    supportedCameras = (camera_unit_t*)calloc(numSupported, sizeof(camera_unit_t));
    if (supportedCameras == NULL) {
        printf("Failed to allocate memory for supported cameras\n");
        return;
    }

    // Get the list of supported cameras
    err = camera_get_supported_cameras(numSupported, &numSupported, supportedCameras);
    if (err != CAMERA_EOK) {
        printf("Failed to get list of supported cameras: err = %d\n", err);
    } else {
        printf("Available camera units:\n");
        for (uint i = 0; i < numSupported; i++) {
            printf("\tCAMERA_UNIT_%d", supportedCameras[i]);
            printf(" (specify -u %d)\n", supportedCameras[i]);
        }
    }

    free(supportedCameras);
    return;
}
