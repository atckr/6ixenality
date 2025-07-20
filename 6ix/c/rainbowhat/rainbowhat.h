/*
 * Copyright (c) 2025, BlackBerry Limited. All rights reserved.
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
 *
* @file rainbowhat.h
* @brief Public API for the Rainbow HAT C library for QNX.
*
* This library provides functions to control the I/O on the Rainbow HAT board.
*  - A/B/C touch pad input buttons
*  - A/B/C output LEDs
*  - RGB LEDs on APA102 (7)
*  - 14-segment alphanumeric display
*  - BMP280 temperature & humidity sensor
*  - Piezo buzzer
*
*/

#ifndef RAINBOWHAT_H
#define RAINBOWHAT_H

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <time.h>
#include <stdbool.h>
 
/* Return Codes */
#define RH_SUCCESS 0
#define RH_FAILURE -1
 
/* Global pointer for accessing GPIO registers */
extern volatile uint32_t *__RPI_GPIO_REGS;

/* --- Pin and GPIO constants. --- */
#define I2C_BUS                 1


/*-----------------------------------------------------------
* Initialization and generic functions
*-----------------------------------------------------------
*/

/**
* @brief Maps the GPIO registers and initializes GPIO.
*
* @return int RH_SUCCESS on success, RH_FAILURE on failure.
*/
int init_gpio(void);


/*-----------------------------------------------------------
* Buttons (A/B/C)
*-----------------------------------------------------------
*/
 
enum Buttons {
    Button_A = 21,
    Button_B = 20,
    Button_C = 16
};

/**
* @brief Initializes a button GPIO as an input with pull-up.
*
* @param button The button, from Buttons.
* @return int RH_SUCCESS on success, RH_FAILURE on failure.
*/
int init_button(enum Buttons button);

/**
* @brief Reads the state of a button.
*
* @param button The button, from Buttons.
* @return bool The button state; true if pressed, false if not pressed.
*/
bool read_button(enum Buttons button);


/*-----------------------------------------------------------
* Plain LEDs (A/B/C)
*-----------------------------------------------------------
*/

enum Leds {
    Led_RED = 6,
    Led_GREEN = 19,
    Led_BLUE = 26
};

/**
* @brief Initializes an LED GPIO for output.
*
* @param led The LED, from Leds.
* @return int RH_SUCCESS on success.
*/
int init_led(enum Leds led);

/**
* @brief Sets the state of an LED.
*
* @param led The LED, from Leds.
* @param state true for ON, false for off.
* @return int RH_SUCCESS on success.
*/
int set_led(enum Leds led, bool state);


/*-----------------------------------------------------------
* RGB LEDs
*-----------------------------------------------------------
*/

#define APA102_DAT              10
#define APA102_CLK              11
#define APA102_CS               8
#define APA102_NUMLEDS          7

/**
* @brief Initializes the APA102 LED driver.
*
* @return int RH_SUCCESS on success, RH_FAILURE on error.
*/
int init_rgb_led(void);

/**
* @brief Sets an RGB LED to a specified color in the buffer. Does not actually change the LEDs until show_rgb_leds() is called.
*
* @param led_index LED index (0..APA102_NUMLEDS-1).
* @param r Red brightness (0-255).
* @param g Green brightness (0-255).
* @param b Blue brightness (0-255).
* @param bightness LED brightness (0-100%).
*/
void set_rgb_led(uint8_t led_index, uint8_t r, uint8_t g, uint8_t b, uint8_t brightness);

/**
* @brief Display the pixel buffer on the LEDs. Change the buffer with set_rgb_led(..).
*
*/
void show_rgb_leds(void);

/**
* @brief Clear the pixel buffer and show the changes -- effectively clear the display.
*
*/
void clear_rbg_leds(void);


/*-----------------------------------------------------------
* Alphanumeric display
*-----------------------------------------------------------
*/

#define HT16K33_ADDR            0x70
#define HT16K33_BLINK_CMD       0x80
#define HT16K33_BLINK_DISPLAYON 0x01
#define HT16K33_SYSTEM_SETUP    0x20
#define HT16K33_OSCILLATOR      0x01
#define HT16K33_CMD_BRIGHTNESS  0xE0

/**
* @brief Initializes the HT16K33 for the alphanumeric display.
*
* @return int RH_SUCCESS on success, RH_FAILURE on error.
*/
int init_alphanum(void);

/**
* @brief Sets a string on the alphanumeric display. Only the first 4 chars will be displayed.
*        Strings should be null terminated (`\0`).
*
* @param *str Character array to display.
*/
void set_alphanum_string(const char *str);

/**
* @brief Sets a number on the alphanumeric display. Handles negative values and decimals.
*
* @param num Number to display.
*/
void set_alphanum_number(double num, bool justify_right);

/**
* @brief Sets a specific character to a specific place on the Alphanumeric display buffer.
*        Does not display on the LEDs until you call show_alphanum().
*
* @param pos The position on the Alphanumeric display (0-3)
* @param digit The ASCII character to display, from ASCII 32 (space) to 126 (tilde)
*/
void set_alphanum_digit(uint8_t pos, unsigned char digit, bool decimal);

/**
* @brief Clears the alphanumeric display of all output.
*
*/
void clear_alphanum(void);

/**
* @brief Outputs the buffer to the Alphanumeric display LEDs.
*
*/
void show_alphanum(void);


/*-----------------------------------------------------------
* Buzzer functions
*-----------------------------------------------------------
*/

#define BUZZER_PIN              13
#define BUZZER_DUTY_CYCLE       50

/**
* @brief Sets the buzzer to play a certain frequency. Use 0 for OFF.
*
* This is a blocking call: the function will delay for the specified duration.
*
* @param freq The musical frequency to play (ex. 440).
* @param millis The duration for which the note should play, in milliseconds.
*/
void set_buzzer_freq(unsigned int freq, uint32_t millis);

/**
* @brief Stops the buzzer from making noise.
*
*/
void stop_buzzer(void);

/*-----------------------------------------------------------
* BMP280 temp/humidity functions
*-----------------------------------------------------------
*/

#define BMP280_ADDR             0x77
#define BMP280_ID               0x58
#define BMP280_QNH              1020
#define BMP280_POWER_MODE       3
#define BMP280_OSRS_T           5 // 20-bit temp resolution
#define BMP280_OSRS_P           5 // 20-bit pressure resolution
#define BMP280_FILTER           4
#define BMP280_T_SB             4 // 500ms standby time
#define BMP280_CONFIG           (BMP280_T_SB << 5) + (BMP280_FILTER << 2) // combine bits for config
#define BMP280_CTRL_MEAS        (BMP280_OSRS_T << 5) + (BMP280_OSRS_P << 2) + BMP280_POWER_MODE // combine bits for ctrl_meas

#define BMP280_DIG_T1          0x88
#define BMP280_DIG_T2          0x8A
#define BMP280_DIG_T3          0x8C
#define BMP280_DIG_P1          0x8E
#define BMP280_DIG_P2          0x90
#define BMP280_DIG_P3          0x92
#define BMP280_DIG_P4          0x94
#define BMP280_DIG_P5          0x96
#define BMP280_DIG_P6          0x98
#define BMP280_DIG_P7          0x9A
#define BMP280_DIG_P8          0x9C
#define BMP280_DIG_P9          0x9E
#define BMP280_CHIPID          0xD0 // Whoami: Expect BMP280_ID (0x58)
#define BMP280_VERSION         0xD1
#define BMP280_SOFTRESET       0xE0
#define BMP280_CONTROL         0xF4
#define BMP280_CONFIG_REG      0xF5
#define BMP280_STATUS          0xF3
#define BMP280_TEMPDATA_MSB    0xFA
#define BMP280_TEMPDATA_LSB    0xFB
#define BMP280_TEMPDATA_XLSB   0xFC
#define BMP280_PRESSDATA_MSB   0xF7
#define BMP280_PRESSDATA_LSB   0xF8
#define BMP280_PRESSDATA_XLSB  0xF9

/**
* @brief Initializes the BMP280 sensor.
*
* @return int RH_SUCCESS on success, RH_FAILURE on error.
*/
int init_bmp(void);

/**
* @brief Gets data from the BMP280 sensor.
*
* @param temperature Pointer to return temperature as a double, in Celcius.
* @param pressure Pointer to return pressure as a double, in hPa.
* 
* @return int RH_SUCCESS on success, RH_FAILURE on error.
*/
int get_bmp_data(double *temperature, double *pressure);

#endif // RAINBOWHAT_H
