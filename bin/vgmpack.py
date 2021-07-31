#!/usr/bin/env python
# python script to pack SN76489 VGM files for use on BBC Micro
# Was previously part of the https://github.com/simondotm/vgm-converter project but now separated out.
# by simondotm
# Released under MIT license
# 


import gzip
import struct
import sys
import binascii
import math
from os.path import basename

if (sys.version_info > (3, 0)):
	from io import BytesIO as ByteBuffer
else:
	from StringIO import StringIO as ByteBuffer



#-----------------------------------------------------------------------------


class FatalError(Exception):
	pass




class VgmStream:


	# VGM commands:
	# 0x50	[dd]	= PSG SN76489 write value dd
	# 0x61	[nnnn]	= WAIT n cycles (0-65535)
	# 0x62			= WAIT 735 samples (1/60 sec)
	# 0x63			= WAIT 882 samples (1/50 sec)
	# 0x66			= END
	# 0x7n			= WAIT n+1 samples (0-15)

	#--------------------------------------------------------------------------------------------------------------------------------
	# SN76489 register writes
	# If bit 7 is 1 then the byte is a LATCH/DATA byte.
	#  %1cctdddd
	#	cc - channel (0-3)
	#	t - type (1 to latch volume, 1 to latch tone/noise)
	#	dddd - placed into the low 4 bits of the relevant register. For the three-bit noise register, the highest bit is discarded.
	#
	# If bit 7 is 0 then the byte is a DATA byte.
	#  %0-DDDDDD
	# If the currently latched register is a tone register then the low 6 bits of the byte (DDDDDD) 
	#	are placed into the high 6 bits of the latched register. If the latched register is less than 6 bits wide 
	#	(ie. not one of the tone registers), instead the low bits are placed into the corresponding bits of the 
	#	register, and any extra high bits are discarded.
	#
	# Tone registers
	#	DDDDDDdddd = cccccccccc
	#	DDDDDDdddd gives the 10-bit half-wave counter reset value.
	#
	# Volume registers
	#	(DDDDDD)dddd = (--vvvv)vvvv
	#	dddd gives the 4-bit volume value.
	#	If a data byte is written, the low 4 bits of DDDDDD update the 4-bit volume value. However, this is unnecessary.
	#
	# Noise register
	#	(DDDDDD)dddd = (---trr)-trr
	#	The low 2 bits of dddd select the shift rate and the next highest bit (bit 2) selects the mode (white (1) or "periodic" (0)).
	#	If a data byte is written, its low 3 bits update the shift rate and mode in the same way.
	#--------------------------------------------------------------------------------------------------------------------------------

	# script vars / configs

	VGM_FREQUENCY = 44100


	# script options
	RETUNE_PERIODIC = True	# [TO BE REMOVED] if true will attempt to retune any use of the periodic noise effect
	VERBOSE = False
	STRIP_GD3 = False	
	LENGTH = 0 # required output length (in seconds)
	
	# VGM file identifier
	vgm_magic_number = b'Vgm '

	disable_dual_chip = True # [TODO] handle dual PSG a bit better

	vgm_source_clock = 0
	vgm_target_clock = 0
	vgm_filename = ''
	vgm_loop_offset = 0
	vgm_loop_length = 0
	
	# Supported VGM versions
	supported_ver_list = [
		0x00000101,
		0x00000110,
		0x00000150,
		0x00000151,
		0x00000160,
		0x00000161,
	]

	# VGM metadata offsets
	metadata_offsets = {
		# SDM Hacked version number 101 too
		0x00000101: {
			'vgm_ident': {'offset': 0x00, 'size': 4, 'type_format': None},
			'eof_offset': {'offset': 0x04, 'size': 4, 'type_format': '<I'},
			'version': {'offset': 0x08, 'size': 4, 'type_format': '<I'},
			'sn76489_clock': {'offset': 0x0c, 'size': 4, 'type_format': '<I'},
			'ym2413_clock': {'offset': 0x10, 'size': 4, 'type_format': '<I'},
			'gd3_offset': {'offset': 0x14, 'size': 4, 'type_format': '<I'},
			'total_samples': {'offset': 0x18, 'size': 4, 'type_format': '<I'},
			'loop_offset': {'offset': 0x1c, 'size': 4, 'type_format': '<I'},
			'loop_samples': {'offset': 0x20, 'size': 4, 'type_format': '<I'},
			'rate': {'offset': 0x24, 'size': 4, 'type_format': '<I'},
			'sn76489_feedback': {
				'offset': 0x28,
				'size': 2,
				'type_format': '<H',
			},
			'sn76489_shift_register_width': {
				'offset': 0x2a,
				'size': 1,
				'type_format': 'B',
			},
			'ym2612_clock': {'offset': 0x2c, 'size': 4, 'type_format': '<I'},
			'ym2151_clock': {'offset': 0x30, 'size': 4, 'type_format': '<I'},
			'vgm_data_offset': {
				'offset': 0x34,
				'size': 4,
				'type_format': '<I',
			},
		},

		# Version 1.10`
		0x00000110: {
			'vgm_ident': {'offset': 0x00, 'size': 4, 'type_format': None},
			'eof_offset': {'offset': 0x04, 'size': 4, 'type_format': '<I'},
			'version': {'offset': 0x08, 'size': 4, 'type_format': '<I'},
			'sn76489_clock': {'offset': 0x0c, 'size': 4, 'type_format': '<I'},
			'ym2413_clock': {'offset': 0x10, 'size': 4, 'type_format': '<I'},
			'gd3_offset': {'offset': 0x14, 'size': 4, 'type_format': '<I'},
			'total_samples': {'offset': 0x18, 'size': 4, 'type_format': '<I'},
			'loop_offset': {'offset': 0x1c, 'size': 4, 'type_format': '<I'},
			'loop_samples': {'offset': 0x20, 'size': 4, 'type_format': '<I'},
			'rate': {'offset': 0x24, 'size': 4, 'type_format': '<I'},
			'sn76489_feedback': {
				'offset': 0x28,
				'size': 2,
				'type_format': '<H',
			},
			'sn76489_shift_register_width': {
				'offset': 0x2a,
				'size': 1,
				'type_format': 'B',
			},
			'ym2612_clock': {'offset': 0x2c, 'size': 4, 'type_format': '<I'},
			'ym2151_clock': {'offset': 0x30, 'size': 4, 'type_format': '<I'},
			'vgm_data_offset': {
				'offset': 0x34,
				'size': 4,
				'type_format': '<I',
			},
		},
		# Version 1.50`
		0x00000150: {
			'vgm_ident': {'offset': 0x00, 'size': 4, 'type_format': None},
			'eof_offset': {'offset': 0x04, 'size': 4, 'type_format': '<I'},
			'version': {'offset': 0x08, 'size': 4, 'type_format': '<I'},
			'sn76489_clock': {'offset': 0x0c, 'size': 4, 'type_format': '<I'},
			'ym2413_clock': {'offset': 0x10, 'size': 4, 'type_format': '<I'},
			'gd3_offset': {'offset': 0x14, 'size': 4, 'type_format': '<I'},
			'total_samples': {'offset': 0x18, 'size': 4, 'type_format': '<I'},
			'loop_offset': {'offset': 0x1c, 'size': 4, 'type_format': '<I'},
			'loop_samples': {'offset': 0x20, 'size': 4, 'type_format': '<I'},
			'rate': {'offset': 0x24, 'size': 4, 'type_format': '<I'},
			'sn76489_feedback': {
				'offset': 0x28,
				'size': 2,
				'type_format': '<H',
			},
			'sn76489_shift_register_width': {
				'offset': 0x2a,
				'size': 1,
				'type_format': 'B',
			},
			'ym2612_clock': {'offset': 0x2c, 'size': 4, 'type_format': '<I'},
			'ym2151_clock': {'offset': 0x30, 'size': 4, 'type_format': '<I'},
			'vgm_data_offset': {
				'offset': 0x34,
				'size': 4,
				'type_format': '<I',
			},
		},
		# SDM Hacked version number, we are happy enough to parse v1.51 as if it were 1.50 since the 1.51 updates dont apply to us anyway
		0x00000151: {
			'vgm_ident': {'offset': 0x00, 'size': 4, 'type_format': None},
			'eof_offset': {'offset': 0x04, 'size': 4, 'type_format': '<I'},
			'version': {'offset': 0x08, 'size': 4, 'type_format': '<I'},
			'sn76489_clock': {'offset': 0x0c, 'size': 4, 'type_format': '<I'},
			'ym2413_clock': {'offset': 0x10, 'size': 4, 'type_format': '<I'},
			'gd3_offset': {'offset': 0x14, 'size': 4, 'type_format': '<I'},
			'total_samples': {'offset': 0x18, 'size': 4, 'type_format': '<I'},
			'loop_offset': {'offset': 0x1c, 'size': 4, 'type_format': '<I'},
			'loop_samples': {'offset': 0x20, 'size': 4, 'type_format': '<I'},
			'rate': {'offset': 0x24, 'size': 4, 'type_format': '<I'},
			'sn76489_feedback': {
				'offset': 0x28,
				'size': 2,
				'type_format': '<H',
			},
			'sn76489_shift_register_width': {
				'offset': 0x2a,
				'size': 1,
				'type_format': 'B',
			},
			'ym2612_clock': {'offset': 0x2c, 'size': 4, 'type_format': '<I'},
			'ym2151_clock': {'offset': 0x30, 'size': 4, 'type_format': '<I'},
			'vgm_data_offset': {
				'offset': 0x34,
				'size': 4,
				'type_format': '<I',
			},
		},
		# SDM Hacked version number, we are happy enough to parse v1.60 as if it were 1.50 since the 1.51 updates dont apply to us anyway
		0x00000160: {
			'vgm_ident': {'offset': 0x00, 'size': 4, 'type_format': None},
			'eof_offset': {'offset': 0x04, 'size': 4, 'type_format': '<I'},
			'version': {'offset': 0x08, 'size': 4, 'type_format': '<I'},
			'sn76489_clock': {'offset': 0x0c, 'size': 4, 'type_format': '<I'},
			'ym2413_clock': {'offset': 0x10, 'size': 4, 'type_format': '<I'},
			'gd3_offset': {'offset': 0x14, 'size': 4, 'type_format': '<I'},
			'total_samples': {'offset': 0x18, 'size': 4, 'type_format': '<I'},
			'loop_offset': {'offset': 0x1c, 'size': 4, 'type_format': '<I'},
			'loop_samples': {'offset': 0x20, 'size': 4, 'type_format': '<I'},
			'rate': {'offset': 0x24, 'size': 4, 'type_format': '<I'},
			'sn76489_feedback': {
				'offset': 0x28,
				'size': 2,
				'type_format': '<H',
			},
			'sn76489_shift_register_width': {
				'offset': 0x2a,
				'size': 1,
				'type_format': 'B',
			},
			'ym2612_clock': {'offset': 0x2c, 'size': 4, 'type_format': '<I'},
			'ym2151_clock': {'offset': 0x30, 'size': 4, 'type_format': '<I'},
			'vgm_data_offset': {
				'offset': 0x34,
				'size': 4,
				'type_format': '<I',
			},
			
		},		
		# SDM Hacked version number, we are happy enough to parse v1.61 as if it were 1.50 since the 1.51 updates dont apply to us anyway
		0x00000161: {
			'vgm_ident': {'offset': 0x00, 'size': 4, 'type_format': None},
			'eof_offset': {'offset': 0x04, 'size': 4, 'type_format': '<I'},
			'version': {'offset': 0x08, 'size': 4, 'type_format': '<I'},
			'sn76489_clock': {'offset': 0x0c, 'size': 4, 'type_format': '<I'},
			'ym2413_clock': {'offset': 0x10, 'size': 4, 'type_format': '<I'},
			'gd3_offset': {'offset': 0x14, 'size': 4, 'type_format': '<I'},
			'total_samples': {'offset': 0x18, 'size': 4, 'type_format': '<I'},
			'loop_offset': {'offset': 0x1c, 'size': 4, 'type_format': '<I'},
			'loop_samples': {'offset': 0x20, 'size': 4, 'type_format': '<I'},
			'rate': {'offset': 0x24, 'size': 4, 'type_format': '<I'},
			'sn76489_feedback': {
				'offset': 0x28,
				'size': 2,
				'type_format': '<H',
			},
			'sn76489_shift_register_width': {
				'offset': 0x2a,
				'size': 1,
				'type_format': 'B',
			},
			'ym2612_clock': {'offset': 0x2c, 'size': 4, 'type_format': '<I'},
			'ym2151_clock': {'offset': 0x30, 'size': 4, 'type_format': '<I'},
			'vgm_data_offset': {
				'offset': 0x34,
				'size': 4,
				'type_format': '<I',
			},
		}
	}

	
	# constructor - pass in the filename of the VGM
	def __init__(self, vgm_filename):

		self.vgm_filename = vgm_filename
		print "  VGM file loaded : '" + vgm_filename + "'"
		
		# open the vgm file and parse it
		vgm_file = open(vgm_filename, 'rb')
		vgm_data = vgm_file.read()
		
		# Store the VGM data and validate it
		self.data = ByteBuffer(vgm_data)
		
		vgm_file.close()
		
		# parse
		self.validate_vgm_data()

		# Set up the variables that will be populated
		self.command_list = []
		self.data_block = None
		self.gd3_data = {}
		self.metadata = {}

		# Parse the VGM metadata and validate the VGM version
		self.parse_metadata()
		
		# Display info about the file
		self.vgm_loop_offset = self.metadata['loop_offset']
		self.vgm_loop_length = self.metadata['loop_samples']
		
		print "      VGM Version : " + "%x" % int(self.metadata['version'])
		print "VGM SN76489 clock : " + str(float(self.metadata['sn76489_clock'])/1000000) + " MHz"
		print "         VGM Rate : " + str(float(self.metadata['rate'])) + " Hz"
		print "      VGM Samples : " + str(int(self.metadata['total_samples'])) + " (" + str(int(self.metadata['total_samples'])/self.VGM_FREQUENCY) + " seconds)"
		print "  VGM Loop Offset : " + str(self.vgm_loop_offset)
		print "  VGM Loop Length : " + str(self.vgm_loop_length)




		# Validation to check we can parse it
		self.validate_vgm_version()

		# Sanity check this VGM is suitable for this script - must be SN76489 only
		if self.metadata['sn76489_clock'] == 0 or self.metadata['ym2413_clock'] !=0 or self.metadata['ym2413_clock'] !=0 or self.metadata['ym2413_clock'] !=0:
			raise FatalError("This script only supports VGM's for SN76489 PSG")		
		
		# see if this VGM uses Dual Chip mode
		if (self.metadata['sn76489_clock'] & 0x40000000) == 0x40000000:
			self.dual_chip_mode_enabled = True
		else:
			self.dual_chip_mode_enabled = False
			
		print "    VGM Dual Chip : " + str(self.dual_chip_mode_enabled)
		

		# override/disable dual chip commands in the output stream if required
		if (self.disable_dual_chip == True) and (self.dual_chip_mode_enabled == True) :
			# remove the clock flag that enables dual chip mode
			self.metadata['sn76489_clock'] = self.metadata['sn76489_clock'] & 0xbfffffff
			self.dual_chip_mode_enabled = False
			print "Dual Chip Mode Disabled - DC Commands will be removed"

		# take a copy of the clock speed for the VGM processor functions
		self.vgm_source_clock = self.metadata['sn76489_clock']
		self.vgm_target_clock = self.vgm_source_clock
		
		# Parse GD3 data and the VGM commands
		self.parse_gd3()
		self.parse_commands()
		
		print "   VGM Commands # : " + str(len(self.command_list))
		print ""


	def validate_vgm_data(self):
		# Save the current position of the VGM data
		original_pos = self.data.tell()

		# Seek to the start of the file
		self.data.seek(0)

		# Perform basic validation on the given file by checking for the VGM
		# magic number ('Vgm ')
		if self.data.read(4) != self.vgm_magic_number:
			# Could not find the magic number. The file could be gzipped (e.g.
			# a vgz file). Try un-gzipping the file and trying again.
			self.data.seek(0)
			self.data = gzip.GzipFile(fileobj=self.data, mode='rb')

			try:
				if self.data.read(4) != self.vgm_magic_number:
					print "Error: Data does not appear to be a valid VGM file"
					raise ValueError('Data does not appear to be a valid VGM file')
			except IOError:
				print "Error: Data does not appear to be a valid VGM file"
				# IOError will be raised if the file is not a valid gzip file
				raise ValueError('Data does not appear to be a valid VGM file')

		# Seek back to the original position in the VGM data
		self.data.seek(original_pos)
		
	def parse_metadata(self):
		# Save the current position of the VGM data
		original_pos = self.data.tell()

		# Create the list to store the VGM metadata
		self.metadata = {}

		# Iterate over the offsets and parse the metadata
		for version, offsets in self.metadata_offsets.items():
			for value, offset_data in offsets.items():

				# Seek to the data location and read the data
				self.data.seek(offset_data['offset'])
				data = self.data.read(offset_data['size'])

				# Unpack the data if required
				if offset_data['type_format'] is not None:
					self.metadata[value] = struct.unpack(
						offset_data['type_format'],
						data,
					)[0]
				else:
					self.metadata[value] = data

		# Seek back to the original position in the VGM data
		self.data.seek(original_pos)

	def validate_vgm_version(self):
		if self.metadata['version'] not in self.supported_ver_list:
			print "VGM version is not supported"
			raise FatalError('VGM version is not supported')

	def parse_gd3(self):
		# Save the current position of the VGM data
		original_pos = self.data.tell()

		# Seek to the start of the GD3 data
		self.data.seek(
			self.metadata['gd3_offset'] +
			self.metadata_offsets[self.metadata['version']]['gd3_offset']['offset']
		)

		# Skip 8 bytes ('Gd3 ' string and 4 byte version identifier)
		self.data.seek(8, 1)

		# Get the length of the GD3 data, then read it
		gd3_length = struct.unpack('<I', self.data.read(4))[0]
		gd3_data = ByteBuffer(self.data.read(gd3_length))

		# Parse the GD3 data
		gd3_fields = []
		current_field = b''
		while True:
			# Read two bytes. All characters (English and Japanese) in the GD3
			# data use two byte encoding
			char = gd3_data.read(2)

			# Break if we are at the end of the GD3 data
			if char == b'':
				break

			# Check if we are at the end of a field, if not then continue to
			# append to "current_field"
			if char == b'\x00\x00':
				gd3_fields.append(current_field)
				current_field = b''
			else:
				current_field += char

		# Once all the fields have been parsed, create a dict with the data
		# some Gd3 tags dont have notes section
		gd3_notes = ''
		gd3_title_eng = basename(self.vgm_filename).encode("utf_16")
		if len(gd3_fields) > 10:
			gd3_notes = gd3_fields[10]
			
		if len(gd3_fields) > 8:
		
			if len(gd3_fields[0]) > 0:
				gd3_title_eng = gd3_fields[0]

				
			self.gd3_data = {
				'title_eng': gd3_title_eng,
				'title_jap': gd3_fields[1],
				'game_eng': gd3_fields[2],
				'game_jap': gd3_fields[3],
				'console_eng': gd3_fields[4],
				'console_jap': gd3_fields[5],
				'artist_eng': gd3_fields[6],
				'artist_jap': gd3_fields[7],
				'date': gd3_fields[8],
				'vgm_creator': gd3_fields[9],
				'notes': gd3_notes
			}		
		else:
			print "WARNING: Malformed/missing GD3 tag"
			self.gd3_data = {
				'title_eng': gd3_title_eng,
				'title_jap': '',
				'game_eng': '',
				'game_jap': '',
				'console_eng': '',
				'console_jap': '',
				'artist_eng': 'Unknown'.encode("utf_16"),
				'artist_jap': '',
				'date': '',
				'vgm_creator': '',
				'notes': ''
			}				


		# Seek back to the original position in the VGM data
		self.data.seek(original_pos)

	#-------------------------------------------------------------------------------------------------

	def parse_commands(self):
		# Save the current position of the VGM data
		original_pos = self.data.tell()

		# Seek to the start of the VGM data
		self.data.seek(
			self.metadata['vgm_data_offset'] +
			self.metadata_offsets[self.metadata['version']]['vgm_data_offset']['offset']
		)

		while True:
			# Read a byte, this will be a VGM command, we will then make
			# decisions based on the given command
			command = self.data.read(1)

			# Break if we are at the end of the file
			if command == '':
				break

			# 0x4f dd - Game Gear PSG stereo, write dd to port 0x06
			# 0x50 dd - PSG (SN76489/SN76496) write value dd
			if command in [b'\x4f', b'\x50']:
				self.command_list.append({
					'command': command,
					'data': self.data.read(1),
				})

			# 0x51 aa dd - YM2413, write value dd to register aa
			# 0x52 aa dd - YM2612 port 0, write value dd to register aa
			# 0x53 aa dd - YM2612 port 1, write value dd to register aa
			# 0x54 aa dd - YM2151, write value dd to register aa
			elif command in [b'\x51', b'\x52', b'\x53', b'\x54']:
				self.command_list.append({
					'command': command,
					'data': self.data.read(2),
				})

			# 0x61 nn nn - Wait n samples, n can range from 0 to 65535
			elif command == b'\x61':
				self.command_list.append({
					'command': command,
					'data': self.data.read(2),
				})

			# 0x62 - Wait 735 samples (60th of a second)
			# 0x63 - Wait 882 samples (50th of a second)
			# 0x66 - End of sound data
			elif command in [b'\x62', b'\x63', b'\x66']:
				self.command_list.append({'command': command, 'data': None})

				# Stop processing commands if we are at the end of the music
				# data
				if command == b'\x66':
					break

			# 0x67 0x66 tt ss ss ss ss - Data block
			elif command == b'\x67':
				# Skip the compatibility and type bytes (0x66 tt)
				self.data.seek(2, 1)

				# Read the size of the data block
				data_block_size = struct.unpack('<I', self.data.read(4))[0]

				# Store the data block for later use
				self.data_block = ByteBuffer(self.data.read(data_block_size))

			# 0x7n - Wait n+1 samples, n can range from 0 to 15
			# 0x8n - YM2612 port 0 address 2A write from the data bank, then
			#        wait n samples; n can range from 0 to 15
			elif b'\x70' <= command <= b'\x8f':
				self.command_list.append({'command': command, 'data': None})

			# 0xe0 dddddddd - Seek to offset dddddddd (Intel byte order) in PCM
			#                 data bank
			elif command == b'\xe0':
				self.command_list.append({
					'command': command,
					'data': self.data.read(4),
				})
				
			# 0x30 dd - dual chip command
			elif command == b'\x30':
				if self.dual_chip_mode_enabled:
					self.command_list.append({
						'command': command,
						'data': self.data.read(1),
					})
			

		# Seek back to the original position in the VGM data
		self.data.seek(original_pos)
		
		
	#-------------------------------------------------------------------------------------------------


	#-------------------------------------------------------------------------------------------------
	def set_verbose(self, verbose):
		self.VERBOSE = verbose

	#-------------------------------------------------------------------------------------------------
	def set_length(self, length):
		self.LENGTH = int(length)


	#-------------------------------------------------------------------------------------------------
		
	# helper function
	# given a start offset (default 0) into the command list, find the next index where
	# the command matches search_command or return -1 if no more of these commands can be found.
	def find_next_command(self, search_command, offset = 0):
		for j in range(offset, len(self.command_list)):
			c = self.command_list[j]["command"]
			
			# only process write data commands
			if c == search_command:
				return j
		else:
			return -1
	
	#-------------------------------------------------------------------------------------------------
	
	# iterate through the command list, removing any write commands that are destined for filter_channel_id
	def filter_channel(self, filter_channel_id):
		print "   VGM Processing : Filtering channel " + str(filter_channel_id)
	
		filtered_command_list = []
		j = 0
		latched_channel = 0
		for q in self.command_list:
			
			# only process write data commands
			if q["command"] != struct.pack('B', 0x50):
				filtered_command_list.append(q)
			else:
				# Check if LATCH/DATA write 								
				qdata = q["data"]
				qw = int(binascii.hexlify(qdata), 16)
				if qw & 128:					
					# Get channel id and latch it
					latched_channel = (qw>>5)&3
					
				if latched_channel != filter_channel_id:
					filtered_command_list.append(q)
		
		self.command_list = filtered_command_list

	#-------------------------------------------------------------------------------------------------
	# iterate through the command list, unpacking any single tone writes on a channel
	def unpack_tones(self):
		print "   VGM Processing : Unpacking tones "
	
		filtered_command_list = []
		j = 0
		latched_channel = 0
		latched_tone_frequencies = [0, 0, 0, 0]
		
		for n in range(len(self.command_list)):
			q = self.command_list[n]
			
			# we always output at least the same data stream, but we might inject a new tone write if needed
			filtered_command_list.append(q)	
			# only process write data commands
			if q["command"] == struct.pack('B', 0x50):
			
				# Check if LATCH/DATA write 								
				qdata = q["data"]
				qw = int(binascii.hexlify(qdata), 16)
				if qw & 128:					
					# Get channel id and latch it
					latched_channel = (qw>>5)&3
					
							
					# Check if TONE update				
					if (qw & 16) == 0:
												
						# get low 4 bits and merge with latched channel's frequency register
						qfreq = (qw & 0b00001111)
						latched_tone_frequencies[latched_channel] = (latched_tone_frequencies[latched_channel] & 0b1111110000) | qfreq

							
						# look ahead, and see if the next command is a DATA write as if so, this will be part of the same tone commmand
						# so load this into our register as well so that we have the correct tone frequency to work with
						
						multi_write = False
						nindex = n
						while (nindex < (len(self.command_list)-1)):# check we dont overflow the array, bail if we do, since it means we didn't find any further DATA writes.
							nindex += 1

							ncommand = self.command_list[nindex]["command"]
							# skip any non-VGM-write commands
							if ncommand != struct.pack('B', 0x50):
								continue
							else:
								# found the next VGM write command
								ndata = self.command_list[nindex]["data"]

								# Check if next this is a DATA write, and capture frequency if so
								# otherwise, its a LATCH/DATA write, so no additional frequency to process
								nw = int(binascii.hexlify(ndata), 16)
								if (nw & 128) == 0:
									multi_write = True
									nfreq = (nw & 0b00111111)
									latched_tone_frequencies[latched_channel] = (latched_tone_frequencies[latched_channel] & 0b0000001111) | (nfreq << 4)	
							
								break					
					
						# if we detected a single register tone write, we need as unpack it, to make sure transposing works correctly
						if multi_write == False and latched_channel != 3:
							if self.VERBOSE: print " UNPACKING SINGLE REGISTER TONE WRITE on CHANNEL " + str(latched_channel)
							# inject additional tone write to prevent any more single register tone writes
							# re-program q and re-cycle it
							
							hi_data = (latched_tone_frequencies[latched_channel]>>4) & 0b00111111
							new_q = { "command" : q["command"], "data" : struct.pack('B', hi_data) }
							filtered_command_list.append(new_q)

		
		self.command_list = filtered_command_list			
	
	#-------------------------------------------------------------------------------------------------
	

	#-------------------------------------------------------------------------------------------------

	def analyse(self):
			

		# now we've quantized we can eliminate redundant register writes
		# for each tone channel
		#  only store the last write
		# for each volume channel
		#  only store the last write
		# maybe incorporate this into the quantization	
			
			
			
			
		# total number of commands in the vgm stream
		num_commands = len(self.command_list)

		# total number of samples in the vgm stream
		total_samples = int(self.metadata['total_samples'])			
			
			
			
			
			
			
		# analysis / output

		minwait = 99999
		minwaitn = 99999
		writecount = 0
		totalwritecount = 0
		maxwritecount = 0
		writedictionary = []
		waitdictionary = []
		tonedictionary = []
		maxtonedata = 0
		numtonedatawrites = 0
		unhandledcommands = 0
		totaltonewrites = 0
		totalvolwrites = 0
		latchtone = 0

		# convert to event sequence, one event per channel, with tones & volumes changed

		#event = { "wait" : 0, "t0" : -1, "v0" : -1, "t1" : -1, "v1" : -1, "t2" : -1, "v2" : -1, "t3" : -1,  "v3" : - 1 }
		event = None

		#nnnnnn tttttt vv ttttt vv tttt vv ttttt vvv

		eventlist = []

		waittime = 0
		tonechannel = 0

		for n in range(num_commands):
			command = self.command_list[n]["command"]
			data = self.command_list[n]["data"]
			pdata = "NONE"
			
			# process command
			if b'\x70' <= command <= b'\x7f':		
				pcommand = "WAITn"
			else:
				pcommand = binascii.hexlify(command)
				
			
				if pcommand == "50":
					pcommand = "WRITE"	
					# count number of serial writes
					writecount += 1
					totalwritecount += 1
					if data not in writedictionary:
						writedictionary.append(data)
				else:
					if writecount > maxwritecount:
						maxwritecount = writecount
					writecount = 0
					if pcommand == "61":
						pcommand = "WAIT "
					else:			
						if pcommand == "66":
							pcommand = "END"
						else:
							if pcommand == "62":
								pcommand = "WAIT60"
							else:
								if pcommand == "63":
									pcommand = "WAIT50"						
								else:
									unhandledcommands += 1
									pdata = "UNKNOWN COMMAND"
									
				



			# process data
			# handle data writes first	
			if pcommand == "WRITE":
			
				# flush any pending wait events
				if waittime > 0:
					# create a new event object, serial writes will be added to this single object
					event = { "wait" : waittime, "t0" : -1, "v0" : -1, "t1" : -1, "v1" : -1, "t2" : -1, "v2" : -1, "t3" : -1,  "v3" : - 1 }	
					eventlist.append(event)
					waittime = 0
					event = None
				
				if event == None:
					event = { "wait" : 0, "t0" : -1, "v0" : -1, "t1" : -1, "v1" : -1, "t2" : -1, "v2" : -1, "t3" : -1,  "v3" : - 1 }	
					
				# process the write data
				pdata = binascii.hexlify(data)
				w = int(pdata, 16)
				s = pdata
				pdata = s + " (" + str(w) + ")"
				if w & 128:
					tonechannel = (w&96)>>5
					pdata += " LATCH"
					pdata += " CH" + str(tonechannel)
					
					if (w & 16):
						pdata += " VOL"
						totalvolwrites += 1
						vol = w & 15
						if tonechannel == 0:
							event["v0"] = vol
						if tonechannel == 1:
							event["v1"] = vol
						if tonechannel == 2:
							event["v2"] = vol
						if tonechannel == 3:
							event["v3"] = vol
							
						
					else:
						pdata += " TONE"
						totaltonewrites += 1
						latchtone = w & 15
					pdata += " " + str(w & 15)
				else:
					pdata += " DATA"
					numtonedatawrites += 1
					if w > maxtonedata:
						maxtonedata = w
					tone = latchtone + (w << 4)
					pdata += " " + str(w) + " (tone=" + str(tone) + ")"
					
					latchtone = 0
					if tone not in tonedictionary:
						tonedictionary.append(tone)
					
					if tonechannel == 0:
						event["t0"] = tone
					if tonechannel == 1:
						event["t1"] = tone
					if tonechannel == 2:
						event["t2"] = tone
					if tonechannel == 3:
						event["t3"] = tone
			else:
				# process wait or end commands
				
				# flush any previously gathered write event
				if event != None:
					eventlist.append(event)
					event = None	
					
				if pcommand == "WAIT60":			
					t = 735
					waittime += t
					if t not in waitdictionary:
						waitdictionary.append(t)

				if pcommand == "WAIT50":
					t = 882
					waittime += t
					if t not in waitdictionary:
						waitdictionary.append(t)	

				if pcommand == "WAIT ":
					pdata = binascii.hexlify(data)
					t = int(pdata, 16)
					# sdm: swap bytes to LSB
					lsb = t & 255
					msb = (t / 256)
					t = (lsb * 256) + msb
					waittime += t
					if t < minwait:
						minwait = t
					ms = t * 1000 / self.VGM_FREQUENCY
					pdata = str(ms) +"ms, " + str(t) + " samples (" + pdata +")"
					if t not in waitdictionary:
						waitdictionary.append(t)					


				if pcommand == "WAITn":
					# data will be "None" for this but thats ok.
					pdata = binascii.hexlify(command)
					t = int(pdata, 16)
					t &= 15
					waittime += t
					if t < minwaitn:
						minwaitn = t
					ms = t * 1000 / self.VGM_FREQUENCY
					pdata = str(ms) +"ms, " + str(t) + " samples (" + pdata +")"
					if t not in waitdictionary:
						waitdictionary.append(t)

				
				

				

			print "#" + str(n) + " Command:" + pcommand + " Data:" + pdata # '{:02x}'.format(data)

		# NOTE: multiple register writes happen instantaneously
		# ideas:
		# quantize tone from 10-bit to 8-bit? Doubt it would sound the same.
		# doesn't seem to be many tone changes, and tones are few in range (i bet vibrato and arpeggios change this though)
		# volume is the main variable - possibly separate the volume stream and resample it?
		# volume can be changed using one byte
		# tone requires two bytes and could be quantized to larger time steps?
		 

		totalwaitcommands = num_commands - totalwritecount
		clockspeed = 2000000
		samplerate = self.VGM_FREQUENCY
		cyclespersample = clockspeed/samplerate


		#--------------------------------
		print "--------------------------------------------------------------------------"
		print "Number of sampled events: " + str(len(eventlist))

		for n in range(len(eventlist)):
			event = eventlist[n]
			print "%6d" % n + " " + str(event)
			

		print "--------------------------------------------------------------------------"

		# compile volume channel 0 stream

		eventlist_v0 = []
		eventlist_v1 = []
		eventlist_v2 = []
		eventlist_v3 = []

		eventlist_t0 = []
		eventlist_t1 = []
		eventlist_t2 = []
		eventlist_t3 = []

		def printEvents(eventlistarray, arrayname):
			print ""
			print "Total " + arrayname + " events: " + str(len(eventlistarray))
			for n in range(len(eventlistarray)):
				event = eventlistarray[n]
				print "%6d" % n + " " + str(event)

		def processEvents(eventsarray_in, eventsarray_out, tag_in, tag_out):
			waittime = 0
			for n in range(len(eventsarray_in)):
				event = eventsarray_in[n]
				t = event["wait"]
				if t > 0:
					waittime += t
				else:
					v = event[tag_in]
					if v > -1:
						eventsarray_out.append({ "wait" : waittime, tag_out : v })
						waittime = 0
						
			printEvents(eventsarray_out, tag_in)

		processEvents(eventlist, eventlist_v0, "v0", "v")
		processEvents(eventlist, eventlist_v1, "v1", "v")
		processEvents(eventlist, eventlist_v2, "v2", "v")
		processEvents(eventlist, eventlist_v3, "v3", "v")

		processEvents(eventlist, eventlist_t0, "t0", "t")
		processEvents(eventlist, eventlist_t1, "t1", "t")
		processEvents(eventlist, eventlist_t2, "t2", "t")
		processEvents(eventlist, eventlist_t3, "t3", "t")				


		# ----------------------- analysis


		print "Number of commands in data file: " + str(num_commands)
		print "Total samples in data file: " + str(total_samples) + " (" + str(total_samples*1000/self.VGM_FREQUENCY) + " ms)"
		print "Smallest wait time was: " + str(minwait) + " samples"
		print "Smallest waitN time was: " + str(minwaitn) + " samples"
		print "ClockSpeed:" + str(clockspeed) + " SampleRate:" + str(samplerate) + " CyclesPerSample:" + str(cyclespersample) + " CyclesPerWrite:" + str(cyclespersample*minwait)
		print "Updates Per Second:" + str(clockspeed/(cyclespersample*minwait))
		print "Total register writes:" + str(totalwritecount) + " Max Sequential Writes:" + str(maxwritecount) # sequential writes happen at same time, in series
		print "Total tone writes:" + str(totaltonewrites)
		print "Total vol writes:" + str(totalvolwrites)
		print "Total wait commands:" + str(totalwaitcommands)
		print "Write dictionary contains " + str(len(writedictionary)) + " unique entries"
		print "Wait dictionary contains " + str(len(waitdictionary)) + " unique entries"
		print "Tone dictionary contains " + str(len(tonedictionary)) + " unique entries"
		print "Largest Tone Data Write value was " + str(maxtonedata)
		print "Number of Tone Data writes was " + str(numtonedatawrites)
		print "Number of unhandled commands was " + str(unhandledcommands)


		estimatedfilesize = totalwritecount + totalwaitcommands

		print "Estimated file size is " + str(estimatedfilesize) + " bytes, assuming 1 byte per command can be achieved"


		print ""

		print "num t0 events: " + str(len(eventlist_t0)) + " (" + str(len(eventlist_t0)*3) + " bytes)"
		print "num t1 events: " + str(len(eventlist_t1)) + " (" + str(len(eventlist_t1)*3) + " bytes)"
		print "num t2 events: " + str(len(eventlist_t2)) + " (" + str(len(eventlist_t2)*3) + " bytes)"
		print "num t3 events: " + str(len(eventlist_t3)) + " (" + str(len(eventlist_t3)*3) + " bytes)"
		print "num v0 events: " + str(len(eventlist_v0)) + " (" + str(len(eventlist_v0)*3) + " bytes)"
		print "num v1 events: " + str(len(eventlist_v1)) + " (" + str(len(eventlist_v1)*3) + " bytes)"
		print "num v2 events: " + str(len(eventlist_v2)) + " (" + str(len(eventlist_v2)*3) + " bytes)"
		print "num v3 events: " + str(len(eventlist_v3)) + " (" + str(len(eventlist_v3)*3) + " bytes)"

		total_volume_events = len(eventlist_v0) + len(eventlist_v1) + len(eventlist_v2) + len(eventlist_v3)
		total_tone_events = len(eventlist_t0) + len(eventlist_t1) + len(eventlist_t2) + len(eventlist_t3)
		size_volume_events = (total_volume_events * 4 / 8) + total_volume_events*2 / 4
		size_tone_events = (total_tone_events * 10 / 8) + total_tone_events*2

		print "total_volume_events = " + str(total_volume_events) + " (" + str(size_volume_events) + " bytes)"
		print "total_tone_events = " + str(total_tone_events) + " (" + str(size_tone_events) + " bytes)"


		# seems you can playback at any frequency, by simply processing the VGM data stream to catchup with the simulated/real time
		# this implies a bunch of registers will be written in one go. So for any tones or volumes that duplicate within the time slot, we can eliminate those
		# therefore, you could in principle 'resample' a VGM at a given update frequency (eg. 50Hz) which would eliminate any redundant data sampled at 44100 hz

		# basically, we'd play the song at a given playback rate, capture the output, and rewrite the VGM with these new values.
		# we can test the process in the web player to see if any fidelity would be lost.
		# at the very least, the wait time numbers would be smaller and therefore easier to pack
		#
		# another solution is to splice a tune into repeated patterns
		#
		# Alternatively, analyse the tune - assuming it was originally sequenced at some BPM, there would have to be a pattern
		# Also, assume that instruments were used where tone/volume envelopes were used
		# Capture when tone changes happen, then look for the volume patterns to create instruments
		# then re-sequence as an instrument/pattern based format	



	# output a binary which has 11 register bytes per frame
	def rawbinary(self):
		# total number of commands in the vgm stream
		num_commands = len(self.command_list)

		# total number of samples in the vgm stream
		total_samples = int(self.metadata['total_samples'])			
			
			
			
			
			
			
		# analysis / output

		minwait = 99999
		minwaitn = 99999
		writecount = 0
		totalwritecount = 0
		maxwritecount = 0
		writedictionary = []
		waitdictionary = []
		tonedictionary = []
		maxtonedata = 0
		numtonedatawrites = 0
		unhandledcommands = 0
		totaltonewrites = 0
		totalvolwrites = 0
		latchtone = 0

		# convert to event sequence, one event per channel, with tones & volumes changed

		#event = { "wait" : 0, "t0" : -1, "v0" : -1, "t1" : -1, "v1" : -1, "t2" : -1, "v2" : -1, "t3" : -1,  "v3" : - 1 }
		event = None

		#nnnnnn tttttt vv ttttt vv tttt vv ttttt vvv

		eventlist = []

		waittime = 0
		tonechannel = 0

		for n in range(num_commands):
			command = self.command_list[n]["command"]
			data = self.command_list[n]["data"]
			pdata = "NONE"
			
			# process command
			if b'\x70' <= command <= b'\x7f':		
				pcommand = "WAITn"
			else:
				pcommand = binascii.hexlify(command)
				
			
				if pcommand == "50":
					pcommand = "WRITE"	
					# count number of serial writes
					writecount += 1
					totalwritecount += 1
					if data not in writedictionary:
						writedictionary.append(data)
				else:
					if writecount > maxwritecount:
						maxwritecount = writecount
					writecount = 0
					if pcommand == "61":
						pcommand = "WAIT "
					else:			
						if pcommand == "66":
							pcommand = "END"
						else:
							if pcommand == "62":
								pcommand = "WAIT60"
							else:
								if pcommand == "63":
									pcommand = "WAIT50"						
								else:
									unhandledcommands += 1
									pdata = "UNKNOWN COMMAND"
									
				



			# process data
			# handle data writes first	
			if pcommand == "WRITE":
			
				# flush any pending wait events
				if waittime > 0:
					# create a new event object, serial writes will be added to this single object
					event = { "wait" : waittime, "t0" : -1, "v0" : -1, "t1" : -1, "v1" : -1, "t2" : -1, "v2" : -1, "t3" : -1,  "v3" : - 1 }	
					eventlist.append(event)
					waittime = 0
					event = None
				
				if event == None:
					event = { "wait" : 0, "t0" : -1, "v0" : -1, "t1" : -1, "v1" : -1, "t2" : -1, "v2" : -1, "t3" : -1,  "v3" : - 1 }	
					
				# process the write data
				pdata = binascii.hexlify(data)
				w = int(pdata, 16)
				s = pdata
				pdata = s + " (" + str(w) + ")"
				if w & 128:
					tonechannel = (w&96)>>5
					pdata += " LATCH"
					pdata += " CH" + str(tonechannel)
					
					if (w & 16):
						pdata += " VOL"
						totalvolwrites += 1
						vol = w & 15
						if tonechannel == 0:
							event["v0"] = vol
						if tonechannel == 1:
							event["v1"] = vol
						if tonechannel == 2:
							event["v2"] = vol
						if tonechannel == 3:
							event["v3"] = vol
							
						
					else:
						pdata += " TONE"
						totaltonewrites += 1
						latchtone = w & 15
					pdata += " " + str(w & 15)
				else:
					pdata += " DATA"
					numtonedatawrites += 1
					if w > maxtonedata:
						maxtonedata = w
					tone = latchtone + (w << 4)
					pdata += " " + str(w) + " (tone=" + str(tone) + ")"
					
					latchtone = 0
					if tone not in tonedictionary:
						tonedictionary.append(tone)
					
					if tonechannel == 0:
						event["t0"] = tone
					if tonechannel == 1:
						event["t1"] = tone
					if tonechannel == 2:
						event["t2"] = tone
					if tonechannel == 3:
						event["t3"] = tone
			else:
				# process wait or end commands
				
				# flush any previously gathered write event
				if event != None:
					eventlist.append(event)
					event = None	
					
				if pcommand == "WAIT60":			
					t = 735
					waittime += t
					if t not in waitdictionary:
						waitdictionary.append(t)

				if pcommand == "WAIT50":
					t = 882
					waittime += t
					if t not in waitdictionary:
						waitdictionary.append(t)	

				if pcommand == "WAIT ":
					pdata = binascii.hexlify(data)
					t = int(pdata, 16)
					# sdm: swap bytes to LSB
					lsb = t & 255
					msb = (t / 256)
					t = (lsb * 256) + msb
					waittime += t
					if t < minwait:
						minwait = t
					ms = t * 1000 / self.VGM_FREQUENCY
					pdata = str(ms) +"ms, " + str(t) + " samples (" + pdata +")"
					if t not in waitdictionary:
						waitdictionary.append(t)					


				if pcommand == "WAITn":
					# data will be "None" for this but thats ok.
					pdata = binascii.hexlify(command)
					t = int(pdata, 16)
					t &= 15
					waittime += t
					if t < minwaitn:
						minwaitn = t
					ms = t * 1000 / self.VGM_FREQUENCY
					pdata = str(ms) +"ms, " + str(t) + " samples (" + pdata +")"
					if t not in waitdictionary:
						waitdictionary.append(t)

				
				

				

			print "#" + str(n) + " Command:" + pcommand + " Data:" + pdata # '{:02x}'.format(data)

		# NOTE: multiple register writes happen instantaneously
		# ideas:
		# quantize tone from 10-bit to 8-bit? Doubt it would sound the same.
		# doesn't seem to be many tone changes, and tones are few in range (i bet vibrato and arpeggios change this though)
		# volume is the main variable - possibly separate the volume stream and resample it?
		# volume can be changed using one byte
		# tone requires two bytes and could be quantized to larger time steps?
		 

		totalwaitcommands = num_commands - totalwritecount
		clockspeed = 2000000
		samplerate = self.VGM_FREQUENCY
		cyclespersample = clockspeed/samplerate


		#--------------------------------
		print "--------------------------------------------------------------------------"
		print "Number of sampled events: " + str(len(eventlist))

		for n in range(len(eventlist)):
			event = eventlist[n]
			print "%6d" % n + " " + str(event)
			

		print "--------------------------------------------------------------------------"

		# compile volume channel 0 stream

		eventlist_v0 = []
		eventlist_v1 = []
		eventlist_v2 = []
		eventlist_v3 = []

		eventlist_t0 = []
		eventlist_t1 = []
		eventlist_t2 = []
		eventlist_t3 = []

		def printEvents(eventlistarray, arrayname):
			print ""
			print "Total " + arrayname + " events: " + str(len(eventlistarray))
			for n in range(len(eventlistarray)):
				event = eventlistarray[n]
				print "%6d" % n + " " + str(event)

		def processEvents(eventsarray_in, eventsarray_out, tag_in, tag_out):
			waittime = 0
			for n in range(len(eventsarray_in)):
				event = eventsarray_in[n]
				t = event["wait"]
				if t > 0:
					waittime += t
				else:
					v = event[tag_in]
					if v > -1:
						eventsarray_out.append({ "wait" : waittime, tag_out : v })
						waittime = 0
						
			printEvents(eventsarray_out, tag_in)

		processEvents(eventlist, eventlist_v0, "v0", "v")
		processEvents(eventlist, eventlist_v1, "v1", "v")
		processEvents(eventlist, eventlist_v2, "v2", "v")
		processEvents(eventlist, eventlist_v3, "v3", "v")

		processEvents(eventlist, eventlist_t0, "t0", "t")
		processEvents(eventlist, eventlist_t1, "t1", "t")
		processEvents(eventlist, eventlist_t2, "t2", "t")
		processEvents(eventlist, eventlist_t3, "t3", "t")				


		# ----------------------- analysis


		print "Number of commands in data file: " + str(num_commands)
		print "Total samples in data file: " + str(total_samples) + " (" + str(total_samples*1000/self.VGM_FREQUENCY) + " ms)"
		print "Smallest wait time was: " + str(minwait) + " samples"
		print "Smallest waitN time was: " + str(minwaitn) + " samples"
		print "ClockSpeed:" + str(clockspeed) + " SampleRate:" + str(samplerate) + " CyclesPerSample:" + str(cyclespersample) + " CyclesPerWrite:" + str(cyclespersample*minwait)
		print "Updates Per Second:" + str(clockspeed/(cyclespersample*minwait))
		print "Total register writes:" + str(totalwritecount) + " Max Sequential Writes:" + str(maxwritecount) # sequential writes happen at same time, in series
		print "Total tone writes:" + str(totaltonewrites)
		print "Total vol writes:" + str(totalvolwrites)
		print "Total wait commands:" + str(totalwaitcommands)
		print "Write dictionary contains " + str(len(writedictionary)) + " unique entries"
		print "Wait dictionary contains " + str(len(waitdictionary)) + " unique entries"
		print "Tone dictionary contains " + str(len(tonedictionary)) + " unique entries"
		print "Largest Tone Data Write value was " + str(maxtonedata)
		print "Number of Tone Data writes was " + str(numtonedatawrites)
		print "Number of unhandled commands was " + str(unhandledcommands)


		estimatedfilesize = totalwritecount + totalwaitcommands

		print "Estimated file size is " + str(estimatedfilesize) + " bytes, assuming 1 byte per command can be achieved"


		print ""

		print "num t0 events: " + str(len(eventlist_t0)) + " (" + str(len(eventlist_t0)*3) + " bytes)"
		print "num t1 events: " + str(len(eventlist_t1)) + " (" + str(len(eventlist_t1)*3) + " bytes)"
		print "num t2 events: " + str(len(eventlist_t2)) + " (" + str(len(eventlist_t2)*3) + " bytes)"
		print "num t3 events: " + str(len(eventlist_t3)) + " (" + str(len(eventlist_t3)*3) + " bytes)"
		print "num v0 events: " + str(len(eventlist_v0)) + " (" + str(len(eventlist_v0)*3) + " bytes)"
		print "num v1 events: " + str(len(eventlist_v1)) + " (" + str(len(eventlist_v1)*3) + " bytes)"
		print "num v2 events: " + str(len(eventlist_v2)) + " (" + str(len(eventlist_v2)*3) + " bytes)"
		print "num v3 events: " + str(len(eventlist_v3)) + " (" + str(len(eventlist_v3)*3) + " bytes)"

		total_volume_events = len(eventlist_v0) + len(eventlist_v1) + len(eventlist_v2) + len(eventlist_v3)
		total_tone_events = len(eventlist_t0) + len(eventlist_t1) + len(eventlist_t2) + len(eventlist_t3)
		size_volume_events = (total_volume_events * 4 / 8) + total_volume_events*2 / 4
		size_tone_events = (total_tone_events * 10 / 8) + total_tone_events*2

		print "total_volume_events = " + str(total_volume_events) + " (" + str(size_volume_events) + " bytes)"
		print "total_tone_events = " + str(total_tone_events) + " (" + str(size_tone_events) + " bytes)"


		# seems you can playback at any frequency, by simply processing the VGM data stream to catchup with the simulated/real time
		# this implies a bunch of registers will be written in one go. So for any tones or volumes that duplicate within the time slot, we can eliminate those
		# therefore, you could in principle 'resample' a VGM at a given update frequency (eg. 50Hz) which would eliminate any redundant data sampled at 44100 hz

		# basically, we'd play the song at a given playback rate, capture the output, and rewrite the VGM with these new values.
		# we can test the process in the web player to see if any fidelity would be lost.
		# at the very least, the wait time numbers would be smaller and therefore easier to pack
		#
		# another solution is to splice a tune into repeated patterns
		#
		# Alternatively, analyse the tune - assuming it was originally sequenced at some BPM, there would have to be a pattern
		# Also, assume that instruments were used where tone/volume envelopes were used
		# Capture when tone changes happen, then look for the volume patterns to create instruments
		# then re-sequence as an instrument/pattern based format	


	#-------------------------------------------------------------------------------------------------
	
	# iterate through the command list, seeing how we might be able to reduce filesize
	# binary format schema is:
	# We assume the VGM has been quantized to fixed intervals. Therefore we do not need to emit wait commands, just packets of data writes.

	# <header>
	#  [byte] - header size - indicates number of bytes in header section
	#  [byte] - indicates the required playback rate in Hz
	#  [byte] - packet count lsb
	#  [byte] - packet count msb
	#  [byte] - duration minutes
	#  [byte] - duration seconds
	# todo: add looping offsets
	# <title>
	#  [byte] - title string size
	#  [dd] ... - ZT title string
	# <author>
	#  [byte] - author string size
	#  [dd] ... - ZT author string
	# <packets>
	#  [byte] - indicating number of data writes within the current packet (max 11)
	#  [dd] ... - data
	#  [byte] - number of data writes within the next packet
	#  [dd] ... - data
	#  ...
	# <eof>
	# [0xff] - eof
	# Max packet length will be 11 bytes as that is all that is needed to update all SN tone + volume registers for all 4 channels in one interval.

	def insights(self):
	
		print "--------------------------------------"
		print "insights"
		print "--------------------------------------"

		packet_dict = []
		volume_packet_dict = []
		tone_packet_dict = []
		
		volume_dict = []
		volume_write_count = 0
		
		tone_dict = []
		tone_latch_write_count = 0
		tone_data_write_count = 0
		tone_single_write_count = 0
		tone_count_7bit = 0

		
		packet_size_counts = [0,0,0,0,0,0,0,0,0,0,0,0,0]
		packet_dict_counts = [0,0,0,0,0,0,0,0,0,0,0,0,0]

		common_packets = 0
		packet_count = 0
		
		packet_block = bytearray()
		volume_packet_block = bytearray()
		tone_packet_block = bytearray()
		
		tone_value = 0
		
		tone_latch_write = False 
		for q in self.command_list:
			
			command = q["command"]
			if command == struct.pack('B', 0x50):
	
				data = q['data']	
				packet_block.extend(data)
				
				w = int(binascii.hexlify(data), 16)		
				
				# gather volume data
				if w & (128+16) == (128+16):
				
					# handle tones where only one write occurred
					if tone_latch_write == True:
						tone_single_write_count += 1
						if tone_value not in tone_dict:
							tone_dict.append(tone_value)
							
					volume_packet_block.extend(data)
					volume_write_count += 1
					if w not in volume_dict:
						volume_dict.append(w)
					tone_latch_write = False

						
				# gather tone latch data
				if w & (128+16) == 128:
					tone_packet_block.extend(data)
					tone_latch_write_count += 1
					
					# handle tones where only one write occurred
					if tone_latch_write == True:
						tone_single_write_count += 1
						if tone_value not in tone_dict:
							tone_dict.append(tone_value)

							
					tone_value = w & 15				
					tone_latch_write = True

				
				# gather tone data
				if (w & 128) == 0:
					if tone_latch_write == False:
						print "ERROR: UNEXPECTED tone data write with no previous latch write"
					tone_packet_block.extend(data)
					tone_data_write_count += 1
					tone_latch_write = False
					tone_value |= (w & 63) << 4
					if tone_value not in tone_dict:
						tone_dict.append(tone_value)

					
			else:
				packet_count += 1
				
				packet_size_counts[len(packet_block)] += 1
				
				# function to compare packets with dictionary library
				# returns true if unique or false if in dictionary
				def process_packet(dict, block):

					# build up a dictionary of packets - curious to see how much repetition exists
					new_packet = True

					for i in range(len(dict)):
						pd = dict[i]
						if len(pd) != len(block):
							#print "Different size - so doesnt match"
							continue
						else:
							#print "Found packet with matching size"
							# same size so compare
							match = True
							for j in range(len(pd)):
								if pd[j] != block[j]:
									match = False
							# we found a match, so it wont be added to the list
							if (match == True):
								new_packet = False
								break
								
					if new_packet == True:
						#print "Non matching - Adding packet"
						dict.append(block)

					return new_packet
			
				# add the various packets to dictionaries so we can determine level of repetition
				process_packet(volume_packet_dict, volume_packet_block)
				process_packet(tone_packet_dict, tone_packet_block)
				
				new_packet = process_packet(packet_dict, packet_block)
				if new_packet == True:
					packet_dict_counts[len(packet_block)] += 1
				
				if False:
					# build up a dictionary of packets - curious to see how much repetition exists
					new_packet = True

					for i in range(len(packet_dict)):
						pd = packet_dict[i]
						if len(pd) != len(packet_block):
							#print "Different size - Adding packet"
							packet_dict.append(packet_block)
							break
						else:
							#print "Found packet with matching size"
							# same size so compare
							mp = True
							for j in range(len(pd)):
								if pd[j] != packet_block[j]:
									mp = False
							if (mp == False):
								new_packet = False
								break
								
					if new_packet == True:
						#print "Non matching - Adding packet"
						packet_dict.append(packet_block)
					else:
						common_packets += 1
						#print "Found matching packet " + str(len(packet_block)) + " bytes"		
				
				# start new packet
				packet_block = bytearray()
				volume_packet_block = bytearray()
				tone_packet_block = bytearray()

				
#		print " Found " + str(common_packets) + " common packets out of total " + str(packet_count) + " packets"

		print " There were " + str(len(packet_dict)) + " unique packets out of total "+ str(packet_count) + " packets"
		print " There were " + str(len(volume_packet_dict)) + " unique volume packets out of total "+ str(packet_count) + " packets"
		print " There were " + str(len(tone_packet_dict)) + " unique tone packets out of total "+ str(packet_count) + " packets"
		print ""
		
		def get_packet_dict_size(dict):
			sz = 0
			for p in dict:
				sz += len(p)
			return sz
			
		print " Packet dictionary size " + str(get_packet_dict_size(packet_dict)) + " bytes"
		print " Volume dictionary size " + str(get_packet_dict_size(volume_packet_dict)) + " bytes"
		print "   Tone dictionary size " + str(get_packet_dict_size(tone_packet_dict)) + " bytes"
		print ""
		
		print " Number of unique volumes " + str(len(volume_dict)) + " (max 64)"	# should max out at 64 (4x16)
		print " Number of volume writes " + str(volume_write_count)
		print ""
		print " Number of unique tones " + str(len(tone_dict))
		print " Number of tone latch writes " + str(tone_latch_write_count)
		print " Number of tone data writes " + str(tone_data_write_count)
		print " Total 16-bit tone data writes " + str(tone_latch_write_count+tone_data_write_count)
		print " Number of single tone latch writes " + str(tone_single_write_count)
		print ""
		print " Packet size distributions (0-11 bytes):"

		t = 0
		for i in range(0,12):
			t += packet_size_counts[i]
		print packet_size_counts, t
			

		print ""
		print " Unique Packet dict distributions (0-11 bytes):"
		t = 0
		for i in range(0,12):
			t += packet_dict_counts[i]
		print packet_dict_counts, t

		print ""
		print " Byte cost distributions (0-11 bytes):"
		o = "[ "
		t = 0
		for i in range(0,12):
			n = (packet_dict_counts[i]) * (i)
			t += n
			o += str(n) + ", "
		print o + "]", t


		print ""
		print " Byte saving distributions (0-11 bytes):"
		t = 0
		o = "[ "
		for i in range(0,12):
			n = (packet_size_counts[i] - packet_dict_counts[i]) * (i)
			t += n
			o += str(n) + ", "
		print o + "]", t



		print ""
		tp = 0
		bs = 0
		size = 1
		for n in packet_size_counts:
			tp += n
			bs += n * size
			size += 1
			
		print " (total packets " + str(tp) + ")"
		print " (total stream bytesize " + str(bs) + ")"
		print " (write count byte size " + str(volume_write_count+tone_latch_write_count+tone_data_write_count+packet_count) + ")"

		print " Volume writes represent " + str( volume_write_count * 100 / (bs-packet_count) ) + " % of filesize"
		print "   Tone writes represent " + str( (tone_latch_write_count+tone_data_write_count) * 100 / (bs-packet_count) ) + " % of filesize"
		
		print " Filesize using packet LUT " + str( packet_count*2 + get_packet_dict_size(packet_dict))
		print " Filesize using vol/tone packet LUT " + str( packet_count*4 + get_packet_dict_size(volume_packet_dict) + get_packet_dict_size(tone_packet_dict) )
		print "--------------------------------------"
	
	#--------------------------------------------------------------------------------------------------------------

	# Apply a sliding window dictionary compression to the packet data
	def compress_packets(self):
	
		print "--------------------------------------"
		print "packet compression"
		print "--------------------------------------"

		packet_list = []
		packet_dict = []

		output_stream = bytearray()
		dict_stream = bytearray()
		
		packet_block = bytearray()

		for q in self.command_list:
			
			command = q["command"]
			if command == struct.pack('B', 0x50):
	
				data = q['data']	
				packet_block.extend(data)

			else:
				packet_list.append(packet_block)

				# start new packet
				packet_block = bytearray()


		print "Found " + str(len(packet_list)) + " packets"


		# approach:
		# as we process each new packet, scan a dictionary memory window to see if already exists
		# if it does, emit an index into the dictionary, otherwise emit the new packet (and add it to the dictionary)

		if True:



			window_size = 2048	# must be power of 2, 2Kb seems to be the sweet spot
			window_size_mask = window_size-1
			window_ptr = 0
			window_data = bytearray()
			for i in range(0,window_size):
				window_data.append(0)

			# process all packets
			# we wont support packets that 'wrap' the window
			for packet in packet_list:


				# see if new packet already exists in dictionary
				packet_index = -1
				packet_size = len(packet)

				# only compress packets of a certain size
				if packet_size > 2:
					for i in range(0, window_size-packet_size):

						# compare window at current index for a packet match
						packet_found = True
						for j in range(len(packet)):
							index = (i+j) # & window_size_mask
							if window_data[index] != packet[j]:
								packet_found = False
								break

						if packet_found:
							packet_index = i

					if packet_index < 0:
						# new packet, so add to dictionary
						if window_ptr+packet_size > window_size:
							window_ptr = 0

						print "New packet added to window index " + str(window_ptr)
						for j in range(packet_size):
							window_data[window_ptr+j] = packet[j]

						window_ptr += packet_size

				# output data
				if packet_index < 0:
					# not found, emit the packet
					output_stream.append(packet_size)
					output_stream.extend(packet)
				else:
					print "Found packet at index " + str(packet_index)
					output_stream.extend(struct.pack('h', packet_index))


			print "Output stream size " + str(len(output_stream))
			bin_file = open("xxx.bin", 'wb')
			bin_file.write(output_stream)
			bin_file.close()				
		else:

			# build up a dictionary of packets - curious to see how much repetition exists


			total_new_packets = 0
			for packet in packet_list:

				packet_index = -1
				# see if new packet already exists in dictionary
				for i in range(len(packet_dict)):
					pd = packet_dict[i]
					if len(pd) != len(packet):
						#print "Different size - so doesnt match"
						continue
					else:
						#print "Found packet with matching size"
						# same size so compare
						match = True
						for j in range(len(pd)):
							if pd[j] != packet[j]:
								match = False
						# we found a match, so set the dictionary index
						if (match == True):
							packet_index = i
							break
							
				if packet_index < 0:
					#print "Non matching - Adding packet"
					packet_index = len(packet_dict)
					packet_dict.append(packet)
					dict_stream.extend(packet)
					total_new_packets += 1

				output_stream.extend(struct.pack('h', packet_index))


			print "Unique packets " + str(total_new_packets)
			print "Dict stream size " + str(len(dict_stream))
			print "Output stream size " + str(len(output_stream))


			# write to output file
			bin_file = open("xxx.bin", 'wb')
			bin_file.write(output_stream)
			bin_file.close()	
			bin_file = open("xxx2.bin", 'wb')
			bin_file.write(dict_stream)
			bin_file.close()			

		print "--------------------------------------"






	
	#--------------------------------------------------------------------------------------------------------------	
	# Write Binary V1 - outputs packets of register data per frame from the VGM stream
	def write_binary(self, filename, rawheader = True):
		print "   VGM Processing : Output binary file "
		
		# debug data to dump out information about the packet stream
		#self.insights()
		#self.compress_packets()
		
		byte_size = 1
		packet_size = 0
		play_rate = self.metadata['rate']
		play_interval = self.VGM_FREQUENCY / play_rate
		data_block = bytearray()
		packet_block = bytearray()

		packet_count = 0
		
		# emit the packet data
		for q in self.command_list:
			
			command = q["command"]
			if command != struct.pack('B', 0x50):
			
				# non-write command, so flush any pending packet data
				if self.VERBOSE: print "Packet length " + str(len(packet_block))

				data_block.append(struct.pack('B', len(packet_block)))
				data_block.extend(packet_block)
				packet_count += 1
				
				#if packet_count > 30*play_rate:
				#	break

				# start new packet
				packet_block = bytearray()
				
				if self.VERBOSE: print "Command " + str(binascii.hexlify(command))
				
				

				# see if command is a wait longer than one interval and emit empty packets to compensate
				wait = 0
				if command == struct.pack('B', 0x61):
					t = int(binascii.hexlify(q["data"]), 16)
					wait = ((t & 255) * 256) + (t>>8)
				else:
					if command == struct.pack('B', 0x62):
						wait = 735
					else:
						if command == struct.pack('B', 0x63):
							wait = 	882
					
				if wait != 0:	
					intervals = wait / (self.VGM_FREQUENCY / play_rate)
					if intervals == 0:
						print "ERROR in data stream, wait value (" + str(wait) + ") was not divisible by play_rate (" + str((self.VGM_FREQUENCY / play_rate)) + "), bailing"
						return
					else:
						if self.VERBOSE: print "WAIT " + str(intervals) + " intervals"
						
					# emit empty packet headers to simulate wait commands
					intervals -= 1
					while intervals > 0:
						data_block.append(0)
						if self.VERBOSE: print "Packet length 0"
						intervals -= 1
						packet_count += 1

				
				
			else:
				if self.VERBOSE: print "Data " + str(binascii.hexlify(command))			
				packet_block.extend(q['data'])

		# eof
		data_block.append(0x00)	# append one last wait
		data_block.append(0xFF)	# signal EOF
		
		
		header_block = bytearray()
		# emit the play rate
		print "play rate is " + str(play_rate)
		header_block.append(struct.pack('B', play_rate & 0xff))
		header_block.append(struct.pack('B', packet_count & 0xff))		
		header_block.append(struct.pack('B', (packet_count >> 8) & 0xff))	

		print "    Num packets " + str(packet_count)
		duration = packet_count / play_rate
		duration_mm = int(duration / 60.0)
		duration_ss = int(duration % 60.0)
		print "    Song duration " + str(duration) + " seconds, " + str(duration_mm) + "m" + str(duration_ss) + "s"
		header_block.append(struct.pack('B', duration_mm))	# minutes		
		header_block.append(struct.pack('B', duration_ss))	# seconds
		
		# output the final byte stream
		output_block = bytearray()	
		
		# send header
		output_block.append(struct.pack('B', len(header_block)))
		output_block.extend(header_block)

		# send title
		title = self.gd3_data['title_eng'].decode("utf_16")
		title = title.encode('ascii', 'ignore')
		
		if len(title) > 254:
			title = title[:254]
		output_block.append(struct.pack('B', len(title) + 1))	# title string length
		output_block.extend(title)
		output_block.append(struct.pack('B', 0))				# zero terminator
		
		# send author
		author = self.gd3_data['artist_eng'].decode("utf_16")
		author = author.encode('ascii', 'ignore')

		# use filename if no author listed
		if len(author) == 0:
			author = basename(self.vgm_filename)

		if len(author) > 254:
			author = author[:254]
		output_block.append(struct.pack('B', len(author) + 1))	# author string length
		output_block.extend(author)
		output_block.append(struct.pack('B', 0))				# zero terminator
		
		# send data with or without header
		if rawheader:
			output_block.extend(data_block)
		else:
			output_block = data_block
		
		# write file
		print "Compressed VGM is " + str(len(output_block)) + " bytes long"

		# write to output file
		bin_file = open(filename, 'wb')
		bin_file.write(output_block)
		bin_file.close()		
		
#------------------------------------------------------------------------------------------
# Main
#------------------------------------------------------------------------------------------

# for testing
my_command_line = None
if False:
	filename = "vgms/sms/10 Page 4.vgm"
	filename = "vgms/sms/18 - 14 Dan's Theme.vgm"
	filename = "vgms/bbc/Galaforce2-title.vgm"
	filename = "vgms/bbc/Firetrack-ingame.vgm"
	filename = "vgms/bbc/CodenameDroid-title.vgm"
	filename = "vgms/sms/07 - 07 COOL JAM.vgm"
	filename = "vgms/sms/09 - 13 Ken's Theme.vgm"
	filename = "vgms/ntsc/15 Diamond Maze.vgm"
	filename = "vgms/ntsc/01 Game Start.vgm"


	#filename = "vgms/ntsc/ne7-magic_beansmaster_system_psg.vgm"
	filename = "vgms/ntsc/Chris Kelly - SMS Power 15th Anniversary Competitions - Collision Chaos.vgz"
	#filename = "vgms/ntsc/BotB 16439 Chip Champion - frozen dancehall of the pharaoh.vgm" # pathological fail, uses the built-in periodic noises which are tuned differently

	#filename = "pn.vgm"
	#filename = "vgms/ntsc/en vard fyra javel.vgm"
	#filename = "chris.vgm"
	filename = "vgms/ntsc/MISSION76496.vgm"
	#filename = "vgms/ntsc/fluid.vgm"
	#filename = "ng.vgm"

	# for testing...
	my_command_line = 'vgmconverter "' + filename + '" -t bbc -q 50 -o "test.vgm"'




#------------------------------------------------------------------------------------------

if my_command_line != None:
	argv = my_command_line.split()
else:
	argv = sys.argv

argc = len(argv)

if argc < 2:
	print "VGM Packing Utility for VGM files based on TI SN76849 sound chips"
	print " Supports gzipped VGM or .vgz files."
	print ""
	print " Usage:"
	print "  vgmpack <vgmfile>  [-filter <n>] [-output <filename>] [-length] [-norawheader] [-dump] [-verbose]"
	print ""
	print "   where:"
	print "    <vgmfile> is the source VGM file to be processed. Wildcards are not yet supported."
	print ""
	print "   options:"
	print "    [-filter <n>, -n <n>] strip one or more output channels from the VGM. For <n> specify a string of channels to filter eg. '0123' or '13' etc."
	print "    [-output <filename>, -o <filename>] output a raw binary file version of the chip data within the source VGM."
	print "    [-length <secs>, -l <secs>] limits output to <secs> seconds. Optional."	
	print "    [-norawheader, -n] removes header from raw file output. Optional."	
	
	print "    [-dump] output human readable version of the VGM"
	print "    [-verbose] enable debug information"
	exit()

# pre-process argv to merge quoted arguments
argi = 0
inquotes = False
outargv = []
quotedarg = []
#print argv
for s in argv:
	#print "s=" + s
	#print "quotedarg=" + str(quotedarg)
	
	if s.startswith('"') and s.endswith('"'):
		outargv.append(s[1:-1])	
		continue
	
	if not inquotes and s.startswith('"'):
		inquotes = True
		quotedarg.append(s[1:] + ' ')
		continue
	
	if inquotes and s.endswith('"'):
		inquotes = False
		quotedarg.append(s[:-1])
		outargv.append("".join(quotedarg))
		quotedarg = []
		continue
		
	if inquotes:
		quotedarg.append(s + ' ')	
		continue
		
	outargv.append(s)

if inquotes:
	print "Error parsing command line " + str(" ".join(argv))
	exit()

argv = outargv
	
# validate source file	
source_filename = None
if argv[1][0] != '-':
	source_filename = argv[1]

# setup option defaults
option_verbose = None
option_filter = None
option_rawfile = None
option_dump = None
option_length = None
option_rawheader = True		# determines if header added to raw output

# process command line
for i in range(2, len(argv)):
	arg = argv[i]
	if arg[0] == '-':
		option = arg[1:].lower()
		if option == 'o' or option == 'output':
			option_rawfile = argv[i+1]
		else:
			if option == 'f' or option == 'filter':
				option_filter = argv[i+1]
			else:
				if option == 'd' or option == 'dump':
					option_dump = True
				else:
					if option == 'v' or option == 'verbose':
						option_verbose = True
					else:
						if option == 'l' or option == 'length':
							option_length = argv[i+1]
						else:
							if option == 'n' or option == 'norawheader':
								option_rawheader = False
							else:
								print "ERROR: Unrecognised option '" + arg + "'"

# load the VGM
if source_filename == None:
	print "ERROR: No source <filename> provided."
	exit()

# if rawfile output is specified, but no quantization option given, force a default quantization of 60Hz (NTSC)
if option_rawfile != None:
	if option_quantize == None:
		option_quantize = 60
	
# debug code	
if False:
	print "source " + str(source_filename)
	print "verbose " + str(option_verbose)
	print "filter " + str(option_filter)
	print "rawfile " + str(option_rawfile)
	print "dump " + str(option_dump)
	print ""


	
vgm_stream = VgmStream(source_filename)

# turn on verbose mode if required
if option_verbose == True:
	vgm_stream.set_verbose(True)
	
# Apply output length if provided
if option_length != None:
	vgm_stream.set_length(option_length)


# apply channel filters
if option_filter != None:
	if option_filter.find('0') != -1:
		vgm_stream.filter_channel(0)
	if option_filter.find('1') != -1:
		vgm_stream.filter_channel(1)
	if option_filter.find('2') != -1:
		vgm_stream.filter_channel(2)
	if option_filter.find('3') != -1:
		vgm_stream.filter_channel(3)


# emit a raw binary file if required, rawheader is on by default
if option_rawfile != None:
	vgm_stream.write_binary(option_rawfile, option_rawheader)

# write out the processed VGM if required
if option_outputfile != None:
	vgm_stream.write_vgm(option_outputfile)

# dump the processed VGM
if option_dump != None:
	vgm_stream.analyse()

# all done
print ""
print "Processing complete."


